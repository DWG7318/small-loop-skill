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


ADDRESS_FIELDS = frozenset({"command", "runtime_root", "timeout_seconds"})
DISPATCH_FIELDS = frozenset({"worker_endpoint", "worker_payload"})
CANDIDATE_FIELDS = frozenset(
    {"repository", "candidate", "cell_goal", "d1_criteria", "evidence_files"}
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
EXPECTED_PROVIDER = "dashscope-tokenplan"
EXPECTED_MODEL = "qwen3.8-max"
VERDICT_EXIT_CODES = {"PASS": 0, "FAIL": 2, "INCOMPLETE": 3}


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
        if endpoint.role != "checker" or endpoint.adapter != "ocrv-checker":
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

    def _candidate_request(self, envelope: Envelope) -> dict[str, Any]:
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
        if not isinstance(value["review_invocation_id"], str) or not value["review_invocation_id"]:
            raise AdapterError("OCRV_RESULT_INVALID", "OCRV review invocation identity is missing")
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
        if review["exit_code"] != process_exit_code:
            raise AdapterError("OCRV_RESULT_INVALID", "OCRV nested exit code mismatch")
        return value

    def _review(
        self,
        endpoint: Endpoint,
        envelope: Envelope,
        attempt: Attempt,
    ) -> DeliveryResult:
        request = self._candidate_request(envelope)
        request_path = attempt.write_json_once("ocrv-request.json", request)
        result_path = attempt.root / "ocrv-result.json"
        command = _string_array(endpoint.address["command"], "command")
        command.extend(["--request", str(request_path), "--output", str(result_path)])
        environment = os.environ.copy()
        environment["OCRV_SLK_RUNTIME_ROOT"] = str(endpoint.address["runtime_root"])
        try:
            completed = subprocess.run(
                command,
                cwd=request["repository"],
                env=environment,
                text=True,
                encoding="utf-8",
                errors="replace",
                capture_output=True,
                timeout=_positive_seconds(endpoint.address["timeout_seconds"]),
                check=False,
            )
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
        attempt.write_json_once(
            "started.json",
            {
                "message_id": envelope.message_id,
                "run_id": envelope.run_id,
                "status": "started",
                "review_invocation_id": result["review_invocation_id"],
                "session_id": review["session_id"],
            },
        )
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
        raise AdapterError("OCRV_PAYLOAD_UNSUPPORTED", "OCRV Checker payload type is unsupported")
