"""OCRV adapter for one exact SLK Checker operation."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import uuid
from dataclasses import asdict
from pathlib import Path
from typing import Any, Mapping

from .base import AdapterError
from ..contracts import (
    ENVELOPE_SCHEMA,
    RESULT_SCHEMA,
    DeliveryResult,
    Endpoint,
    Envelope,
    canonical_json_sha256,
)
from ..evidence import Attempt
from ..process import windows_no_window_kwargs
from ..subprocess_watch import finish, spawn


ADDRESS_FIELDS = frozenset({"command", "runtime_root", "timeout_seconds"})
DISPATCH_FIELDS = frozenset({"worker_endpoint", "worker_payload"})
CANDIDATE_FIELDS = frozenset(
    {"repository", "candidate", "cell_goal", "d1_criteria", "evidence_files"}
)
RECOVERY_FIELDS = frozenset(
    {
        "source_attempt_root",
        "runtime_projection_path",
        "plan_revision",
        "runtime_revision",
        "token_sequence",
        "worker_credential_path",
        "checker_credential_path",
        "state_command",
        "transport_command",
        "occurred_at",
    }
)
OCRV_RESULT_FIELDS = frozenset(
    {
        "schema_version",
        "run_id",
        "cell_id",
        "review_invocation_id",
        "verdict",
        "reason_codes",
        "findings",
        "review",
        "evidence",
        "request_sha256",
        "artifacts",
    }
)
OCRV_REVIEW_FIELDS = frozenset({"status", "provider", "model", "session_id", "exit_code"})
RECOVERY_RESULT_FIELDS = frozenset(
    {
        "schema_version",
        "method_version",
        "status",
        "run_id",
        "cell_id",
        "source_message_id",
        "worker_session_id",
        "checker_role_instance_id",
        "checker_endpoint_version",
        "checker_authenticated",
        "authorized_recovery",
        "recovery_invocation_id",
        "request_sha256",
    }
)
EXPECTED_PROVIDER = "dashscope-tokenplan"
EXPECTED_MODEL = "qwen3.8-max"
VERDICT_EXIT_CODES = {"PASS": 0, "FAIL": 2, "INCOMPLETE": 3}
RECOVERY_NAMESPACE = uuid.UUID("9ae86847-8f6f-4b71-9288-18cf7f8f8540")


def _recovery_invocation_id(message_id: str) -> str:
    return str(uuid.uuid5(RECOVERY_NAMESPACE, f"{message_id}:worker-completion-recovery"))


def _positive_seconds(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        raise AdapterError("OCRV_ADDRESS_INVALID", "timeout_seconds must be positive")
    return float(value)


def _string_array(value: Any, label: str) -> list[str]:
    if not isinstance(value, list) or not value or not all(isinstance(item, str) and item for item in value):
        raise AdapterError("OCRV_ADDRESS_INVALID", f"{label} must be a non-empty string array")
    return list(value)


def _closed(value: Mapping[str, Any], fields: frozenset[str], label: str) -> None:
    if set(value) != fields:
        raise AdapterError("OCRV_PAYLOAD_INVALID", f"{label} must use the exact field set")


def _nonempty(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AdapterError("OCRV_PAYLOAD_INVALID", f"{label} must be a non-empty string")
    return value.strip()


class OcrvAdapter:
    def validate_address(self, endpoint: Endpoint) -> None:
        if (
            endpoint.role != "checker"
            or endpoint.agent_runtime != "ocrv"
            or endpoint.adapter != "ocrv-checker"
        ):
            raise AdapterError("OCRV_ADDRESS_INVALID", "OCRV endpoint must be the Checker adapter")
        address = endpoint.address
        if set(address) != ADDRESS_FIELDS:
            raise AdapterError("OCRV_ADDRESS_INVALID", "OCRV address must use the exact field set")
        _string_array(address["command"], "command")
        runtime_root = address["runtime_root"]
        if (
            not isinstance(runtime_root, str)
            or not Path(runtime_root).is_absolute()
            or not Path(runtime_root).is_dir()
        ):
            raise AdapterError("OCRV_ADDRESS_INVALID", "runtime_root must be an existing absolute directory")
        _positive_seconds(address["timeout_seconds"])

    def _dispatch(
        self,
        endpoint: Endpoint,
        envelope: Envelope,
        attempt: Attempt,
    ) -> DeliveryResult:
        payload = envelope.payload
        _closed(payload, DISPATCH_FIELDS, "CELL_DISPATCH payload")
        try:
            worker = Endpoint.from_dict(payload["worker_endpoint"])  # type: ignore[arg-type]
        except (TypeError, ValueError) as exc:
            raise AdapterError("OCRV_PAYLOAD_INVALID", "worker_endpoint is invalid") from exc
        if worker.run_id != envelope.run_id or worker.role != "worker" or worker.state != "active":
            raise AdapterError("OCRV_PAYLOAD_INVALID", "worker_endpoint is not an active Worker in this Run")
        worker_payload = payload["worker_payload"]
        if not isinstance(worker_payload, Mapping):
            raise AdapterError("OCRV_PAYLOAD_INVALID", "worker_payload must be an object")
        next_raw = {
            "schema_version": ENVELOPE_SCHEMA,
            "message_id": str(uuid.uuid4()),
            "token_sequence": envelope.token_sequence + 1,
            "run_id": envelope.run_id,
            "go_id": envelope.go_id,
            "cell_id": envelope.cell_id,
            "sender_role": "checker",
            "sender_role_instance_id": endpoint.role_instance_id,
            "receiver_role": "worker",
            "receiver_role_instance_id": worker.role_instance_id,
            "receiver_endpoint_version": worker.endpoint_version,
            "payload_type": "WORKER_TASK",
            "payload_sha256": canonical_json_sha256(worker_payload),
            "payload": worker_payload,
        }
        next_envelope = Envelope.from_dict(next_raw)
        attempt.write_json_once(
            "started.json",
            {
                "message_id": envelope.message_id,
                "run_id": envelope.run_id,
                "status": "started",
                "checker_operation": "dispatch",
            },
        )
        attempt.write_json_once(
            "checker-result.json",
            {
                "schema_version": "slk.checker-result/v1",
                "operation": "dispatch",
                "source_message_id": envelope.message_id,
                "next_endpoint": asdict(worker),
                "next_envelope": asdict(next_envelope),
            },
        )
        return DeliveryResult(
            schema_version=RESULT_SCHEMA,
            message_id=envelope.message_id,
            run_id=envelope.run_id,
            adapter=endpoint.adapter,
            status="completed",
            native_identity={
                "checker_operation": "dispatch",
                "role_instance_id": endpoint.role_instance_id,
            },
            error_code=None,
            evidence=("started.json", "checker-result.json"),
        )

    def _candidate_request(self, envelope: Envelope, review_invocation_id: str) -> dict[str, Any]:
        payload = envelope.payload
        _closed(payload, CANDIDATE_FIELDS, "CANDIDATE_READY payload")
        repository = Path(_nonempty(payload["repository"], "repository"))
        if not repository.is_absolute() or not repository.is_dir():
            raise AdapterError("OCRV_PAYLOAD_INVALID", "repository must be an existing absolute directory")
        candidate = payload["candidate"]
        if not isinstance(candidate, Mapping):
            raise AdapterError("OCRV_PAYLOAD_INVALID", "candidate must be an object")
        criteria = payload["d1_criteria"]
        if not isinstance(criteria, list) or not criteria or not all(
            isinstance(item, str) and item.strip() for item in criteria
        ):
            raise AdapterError("OCRV_PAYLOAD_INVALID", "d1_criteria must be a non-empty string array")
        evidence_files = payload["evidence_files"]
        if not isinstance(evidence_files, list) or not all(
            isinstance(item, str) and Path(item).is_absolute() and Path(item).is_file()
            for item in evidence_files
        ):
            raise AdapterError("OCRV_PAYLOAD_INVALID", "evidence_files must contain existing absolute files")
        return {
            "schema_version": "slk.ocrv-d1-request/v1",
            "run_id": envelope.run_id,
            "cell_id": envelope.cell_id,
            "review_invocation_id": review_invocation_id,
            "repository": str(repository.resolve()),
            "candidate": dict(candidate),
            "cell_goal": _nonempty(payload["cell_goal"], "cell_goal"),
            "d1_criteria": [item.strip() for item in criteria],
            "evidence_files": list(evidence_files),
        }

    def _read_ocrv_result(
        self,
        path: Path,
        request_path: Path,
        envelope: Envelope,
        process_exit_code: int,
    ) -> Mapping[str, Any]:
        try:
            value = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError) as exc:
            raise AdapterError("OCRV_RESULT_INVALID", "OCRV result is missing or invalid JSON") from exc
        if not isinstance(value, dict) or set(value) != OCRV_RESULT_FIELDS:
            raise AdapterError("OCRV_RESULT_INVALID", "OCRV result does not use the closed field set")
        if value["schema_version"] != "slk.ocrv-d1-result/v1":
            raise AdapterError("OCRV_RESULT_INVALID", "OCRV result schema mismatch")
        if value["run_id"] != envelope.run_id or value["cell_id"] != envelope.cell_id:
            raise AdapterError("OCRV_RESULT_INVALID", "OCRV Run or CELL identity mismatch")
        request = json.loads(request_path.read_text(encoding="utf-8-sig"))
        if value["review_invocation_id"] != request.get("review_invocation_id"):
            raise AdapterError("OCRV_RESULT_INVALID", "OCRV review invocation identity mismatch")
        verdict = value["verdict"]
        if verdict not in VERDICT_EXIT_CODES or VERDICT_EXIT_CODES[verdict] != process_exit_code:
            raise AdapterError("OCRV_RESULT_INVALID", "OCRV verdict and process exit code disagree")
        if not isinstance(value["reason_codes"], list) or not all(
            isinstance(item, str) and item for item in value["reason_codes"]
        ):
            raise AdapterError("OCRV_RESULT_INVALID", "OCRV reason_codes are invalid")
        if not isinstance(value["findings"], list) or not isinstance(value["evidence"], list):
            raise AdapterError("OCRV_RESULT_INVALID", "OCRV finding or evidence arrays are invalid")
        if not isinstance(value["artifacts"], dict):
            raise AdapterError("OCRV_RESULT_INVALID", "OCRV artifacts must be an object")
        expected_request_sha = hashlib.sha256(request_path.read_bytes()).hexdigest()
        if value["request_sha256"] != expected_request_sha:
            raise AdapterError("OCRV_RESULT_INVALID", "OCRV request hash mismatch")
        review = value["review"]
        if not isinstance(review, dict) or set(review) != OCRV_REVIEW_FIELDS:
            raise AdapterError("OCRV_RESULT_INVALID", "OCRV review identity is not closed")
        if review["provider"] != EXPECTED_PROVIDER or review["model"] != EXPECTED_MODEL:
            raise AdapterError("OCRV_RESULT_INVALID", "OCRV provider or model mismatch")
        if not isinstance(review["session_id"], str) or not review["session_id"]:
            raise AdapterError("OCRV_RESULT_INVALID", "OCRV session identity is missing")
        if isinstance(review["exit_code"], bool) or not isinstance(review["exit_code"], int):
            raise AdapterError("OCRV_RESULT_INVALID", "OCRV nested review exit code is invalid")
        return value

    def _recovery_request(
        self,
        endpoint: Endpoint,
        envelope: Envelope,
        recovery_invocation_id: str,
        result_path: Path,
    ) -> dict[str, Any]:
        payload = envelope.payload
        _closed(payload, RECOVERY_FIELDS, "WORKER_COMPLETION_RECOVERY payload")
        paths: dict[str, str] = {}
        for field in (
            "source_attempt_root",
            "runtime_projection_path",
            "worker_credential_path",
            "checker_credential_path",
        ):
            path = Path(_nonempty(payload[field], field))
            expected = path.is_dir() if field == "source_attempt_root" else path.is_file()
            if not path.is_absolute() or not expected:
                raise AdapterError("OCRV_PAYLOAD_INVALID", f"{field} must name an existing absolute path")
            paths[field] = str(path.resolve())
        revisions: dict[str, int] = {}
        for field in ("plan_revision", "runtime_revision", "token_sequence"):
            value = payload[field]
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise AdapterError("OCRV_PAYLOAD_INVALID", f"{field} must be a positive integer")
            revisions[field] = value
        state_command = _string_array(payload["state_command"], "state_command")
        transport_command = _string_array(payload["transport_command"], "transport_command")
        return {
            "schema_version": "slk.ocrv-worker-recovery-request/v1",
            "method_version": "4.2.6",
            "recovery_invocation_id": recovery_invocation_id,
            "recovery_envelope_message_id": envelope.message_id,
            "run_id": envelope.run_id,
            "go_id": envelope.go_id,
            "cell_id": envelope.cell_id,
            "checker_role_instance_id": endpoint.role_instance_id,
            "checker_endpoint_version": endpoint.endpoint_version,
            "checker_endpoint": asdict(endpoint),
            **paths,
            **revisions,
            "state_command": state_command,
            "transport_command": transport_command,
            "occurred_at": _nonempty(payload["occurred_at"], "occurred_at"),
            "result_path": str(result_path.resolve()),
        }

    def _read_recovery_result(
        self,
        path: Path,
        request_path: Path,
        endpoint: Endpoint,
        envelope: Envelope,
        recovery_invocation_id: str,
    ) -> Mapping[str, Any]:
        try:
            value = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError) as exc:
            raise AdapterError("OCRV_RECOVERY_RESULT_INVALID", "Checker recovery result is unavailable") from exc
        if not isinstance(value, dict) or set(value) != RECOVERY_RESULT_FIELDS:
            raise AdapterError("OCRV_RECOVERY_RESULT_INVALID", "Checker recovery result is not closed")
        if (
            value["schema_version"] != "slk.ocrv-worker-recovery-result/v1"
            or value["method_version"] != "4.2.6"
            or value["status"] != "CHECKER_STARTED"
            or value["run_id"] != envelope.run_id
            or value["cell_id"] != envelope.cell_id
            or value["checker_role_instance_id"] != endpoint.role_instance_id
            or value["checker_endpoint_version"] != endpoint.endpoint_version
            or value["checker_authenticated"] is not True
            or value["authorized_recovery"] is not True
            or value["recovery_invocation_id"] != recovery_invocation_id
            or value["request_sha256"] != hashlib.sha256(request_path.read_bytes()).hexdigest()
        ):
            raise AdapterError("OCRV_RECOVERY_RESULT_INVALID", "Checker recovery identity does not match")
        return value

    def _recover(
        self,
        endpoint: Endpoint,
        envelope: Envelope,
        attempt: Attempt,
    ) -> DeliveryResult:
        recovery_invocation_id = _recovery_invocation_id(envelope.message_id)
        result_path = attempt.root / "ocrv-recovery-result.json"
        request = self._recovery_request(endpoint, envelope, recovery_invocation_id, result_path)
        request_path = attempt.write_json_once("ocrv-recovery-request.json", request)
        command = _string_array(endpoint.address["command"], "command")
        command.extend(
            [
                "--slk-worker-recovery",
                "--request",
                str(request_path),
                "--output",
                str(result_path),
            ]
        )
        environment = os.environ.copy()
        environment.pop("SLK_ROLE_CREDENTIAL", None)
        environment.pop("SLK_OVERWATCHER_CREDENTIAL", None)
        environment["SLK_OCRV_RECOVERY_ROLE_INSTANCE_ID"] = endpoint.role_instance_id
        environment["SLK_OCRV_RECOVERY_INVOCATION_ID"] = recovery_invocation_id
        environment["SLK_OCRV_RECOVERY_ENDPOINT_VERSION"] = str(endpoint.endpoint_version)
        process = spawn(
            command,
            cwd=str(Path(request["source_attempt_root"])),
            env=environment,
            process_kwargs=windows_no_window_kwargs(),
        )
        attempt.write_json_once(
            "started.json",
            {
                "message_id": envelope.message_id,
                "run_id": envelope.run_id,
                "status": "started",
                "checker_operation": "worker_completion_recovery",
                "checker_role_instance_id": endpoint.role_instance_id,
                "checker_endpoint_version": endpoint.endpoint_version,
                "recovery_invocation_id": recovery_invocation_id,
                "authentication_status": "PENDING",
                "authorized_recovery": False,
            },
        )
        try:
            completed = finish(process, _positive_seconds(endpoint.address["timeout_seconds"]))
        except subprocess.TimeoutExpired as exc:
            raise AdapterError("OCRV_RECOVERY_TIMEOUT", "Checker recovery did not complete in time") from exc
        attempt.write_text_once("native.stdout.txt", completed.stdout)
        attempt.write_text_once("native.stderr.txt", completed.stderr)
        if completed.returncode != 0:
            raise AdapterError("OCRV_RECOVERY_FAILED", "Checker recovery process failed")
        result = self._read_recovery_result(
            result_path,
            request_path,
            endpoint,
            envelope,
            recovery_invocation_id,
        )
        return DeliveryResult(
            schema_version=RESULT_SCHEMA,
            message_id=envelope.message_id,
            run_id=envelope.run_id,
            adapter=endpoint.adapter,
            status="completed",
            native_identity={
                "checker_operation": "worker_completion_recovery",
                "checker_role_instance_id": endpoint.role_instance_id,
                "checker_endpoint_version": endpoint.endpoint_version,
                "recovery_invocation_id": recovery_invocation_id,
                "source_message_id": result["source_message_id"],
                "worker_session_id": result["worker_session_id"],
                "checker_authenticated": True,
                "authorized_recovery": True,
            },
            error_code=None,
            evidence=(
                "started.json",
                "ocrv-recovery-request.json",
                "ocrv-recovery-result.json",
                "native.stdout.txt",
                "native.stderr.txt",
            ),
        )

    def _review(
        self,
        endpoint: Endpoint,
        envelope: Envelope,
        attempt: Attempt,
    ) -> DeliveryResult:
        review_invocation_id = str(uuid.uuid4())
        request = self._candidate_request(envelope, review_invocation_id)
        request_path = attempt.write_json_once("ocrv-request.json", request)
        result_path = attempt.root / "ocrv-result.json"
        command = _string_array(endpoint.address["command"], "command")
        command.extend(["--request", str(request_path), "--output", str(result_path)])
        environment = os.environ.copy()
        environment.pop("SLK_ROLE_CREDENTIAL", None)
        environment.pop("SLK_OVERWATCHER_CREDENTIAL", None)
        environment["OCRV_SLK_RUNTIME_ROOT"] = str(endpoint.address["runtime_root"])
        try:
            process = spawn(
                command,
                cwd=str(request["repository"]),
                env=environment,
                process_kwargs=windows_no_window_kwargs(),
            )
            attempt.write_json_once(
                "started.json",
                {
                    "message_id": envelope.message_id,
                    "run_id": envelope.run_id,
                    "status": "started",
                    "review_invocation_id": review_invocation_id,
                },
            )
            completed = finish(process, _positive_seconds(endpoint.address["timeout_seconds"]))
        except subprocess.TimeoutExpired as exc:
            stdout = exc.stdout if isinstance(exc.stdout, str) else ""
            stderr = exc.stderr if isinstance(exc.stderr, str) else ""
            attempt.write_text_once("native.stdout.txt", stdout)
            attempt.write_text_once("native.stderr.txt", stderr)
            raise AdapterError("OCRV_TIMEOUT", "OCRV Checker did not complete in time") from exc
        attempt.write_text_once("native.stdout.txt", completed.stdout)
        attempt.write_text_once("native.stderr.txt", completed.stderr)
        result = self._read_ocrv_result(
            result_path,
            request_path,
            envelope,
            completed.returncode,
        )
        review = result["review"]
        return DeliveryResult(
            schema_version=RESULT_SCHEMA,
            message_id=envelope.message_id,
            run_id=envelope.run_id,
            adapter=endpoint.adapter,
            status="completed",
            native_identity={
                "run_id": envelope.run_id,
                "cell_id": envelope.cell_id,
                "review_invocation_id": result["review_invocation_id"],
                "session_id": review["session_id"],
                "provider": review["provider"],
                "model": review["model"],
                "verdict": result["verdict"],
                "exit_code": completed.returncode,
            },
            error_code=None,
            evidence=(
                "started.json",
                "ocrv-request.json",
                "ocrv-result.json",
                "native.stdout.txt",
                "native.stderr.txt",
            ),
        )

    def deliver(self, endpoint: Endpoint, envelope: Envelope, attempt: Attempt) -> DeliveryResult:
        self.validate_address(endpoint)
        if envelope.payload_type == "CELL_DISPATCH":
            return self._dispatch(endpoint, envelope, attempt)
        if envelope.payload_type == "CANDIDATE_READY":
            return self._review(endpoint, envelope, attempt)
        if envelope.payload_type == "WORKER_COMPLETION_RECOVERY":
            return self._recover(endpoint, envelope, attempt)
        raise AdapterError("OCRV_PAYLOAD_UNSUPPORTED", "OCRV Checker payload type is unsupported")
