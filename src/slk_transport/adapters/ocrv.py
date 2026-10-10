"""OCRV adapter for one exact SLK Checker operation."""

from __future__ import annotations

from .. import SUPPORTED_METHOD_VERSIONS

import hashlib
import json
import os
import subprocess
import time
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
from ..native_activity import (
    NativeActivityError,
    make_native_start,
    validate_native_start,
)
from ..process import windows_no_window_kwargs
from ..subprocess_watch import finish, spawn


ADDRESS_FIELDS = frozenset({"command", "runtime_root", "timeout_seconds"})
REVIEW_CAPACITY_FIELDS = frozenset({"max_tokens", "max_tokens_budget", "timeout_minutes"})
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
PRE_D0_RECOVERY_FIELDS = RECOVERY_FIELDS | {
    "environment_adjustment_path",
    "environment_adjustment_sha256",
}
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
OCRV_PREFLIGHT_FIELDS = frozenset(
    {"schema_version", "status", "run_id", "cell_id", "request_sha256", "background", "preview", "scope", "capabilities"}
)
OCRV_PREFLIGHT_BACKGROUND_FIELDS = frozenset(
    {"characters", "bytes", "evidence_bytes", "sha256"}
)
OCRV_PREFLIGHT_PREVIEW_FIELDS = frozenset(
    {"exit_code", "selected_paths", "inventory", "stdout_sha256", "stderr_sha256"}
)
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
        "runtime_revision",
        "token_sequence",
        "checker_token_already_committed",
        "native_attempt_path",
        "d1_verdict",
        "d1_event_type",
        "native_result_path",
    }
)
EXPECTED_PROVIDER = "dashscope-tokenplan"
EXPECTED_MODEL = "qwen3.8-max"
VERDICT_EXIT_CODES = {"PASS": 0, "FAIL": 2, "INCOMPLETE": 3}
DEFAULT_REVIEW_CAPACITY = {
    "max_background_characters": 8_000,
    "max_background_bytes": 12_000,
    "max_changed_lines": 800,
    "max_segment_paths": 2,
    "max_tokens": 200_000,
    "max_tokens_budget": 0,
    "timeout_minutes": 0,
}
RECOVERY_NAMESPACE = uuid.UUID("9ae86847-8f6f-4b71-9288-18cf7f8f8540")


def _recovery_invocation_id(message_id: str) -> str:
    return str(uuid.uuid5(RECOVERY_NAMESPACE, f"{message_id}:worker-completion-recovery"))


def _positive_seconds(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        raise AdapterError("OCRV_ADDRESS_INVALID", "timeout_seconds must be positive")
    return float(value)


def _positive_integer(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise AdapterError("OCRV_ADDRESS_INVALID", f"{label} must be a positive integer")
    return value


def _nonnegative_integer(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise AdapterError("OCRV_ADDRESS_INVALID", f"{label} must be a non-negative integer")
    return value


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


def _checker_process_kwargs() -> dict[str, Any]:
    return windows_no_window_kwargs()


def _native_start_context(
    endpoint: Endpoint,
    envelope: Envelope,
    native_request_sha256: str,
) -> dict[str, str]:
    return {
        "adapter": endpoint.adapter,
        "run_id": envelope.run_id,
        "cell_id": envelope.cell_id,
        "message_id": envelope.message_id,
        "request_sha256": envelope.payload_sha256,
        "native_request_sha256": native_request_sha256,
    }


def _await_native_start(
    process: subprocess.Popen[str],
    receipt_path: Path,
    endpoint: Endpoint,
    envelope: Envelope,
    native_request_sha256: str,
    timeout: float,
) -> dict[str, Any]:
    deadline = time.monotonic() + min(timeout, 30.0)
    while time.monotonic() < deadline:
        if receipt_path.is_file():
            try:
                return validate_native_start(
                    receipt_path,
                    adapter=endpoint.adapter,
                    run_id=envelope.run_id,
                    cell_id=envelope.cell_id,
                    message_id=envelope.message_id,
                    request_sha256=envelope.payload_sha256,
                    native_request_sha256=native_request_sha256,
                )
            except NativeActivityError as exc:
                if "unreadable" not in str(exc) or process.poll() is not None:
                    raise AdapterError("OCRV_NATIVE_START_INVALID", str(exc)) from exc
        if process.poll() is not None:
            break
        time.sleep(0.01)
    raise AdapterError(
        "OCRV_NATIVE_START_UNPROVED",
        "OCRV child did not publish one matching native-start receipt",
    )


def _arm_child_start(
    environment: dict[str, str],
    receipt_path: Path,
    endpoint: Endpoint,
    envelope: Envelope,
    native_request_sha256: str,
) -> None:
    environment["SLK_NATIVE_START_RECEIPT"] = str(receipt_path)
    environment["SLK_NATIVE_START_CONTEXT"] = json.dumps(
        _native_start_context(endpoint, envelope, native_request_sha256),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


class OcrvAdapter:
    def validate_address(self, endpoint: Endpoint) -> None:
        if (
            endpoint.role != "checker"
            or endpoint.agent_runtime != "ocrv"
            or endpoint.adapter != "ocrv-checker"
        ):
            raise AdapterError("OCRV_ADDRESS_INVALID", "OCRV endpoint must be the Checker adapter")
        address = endpoint.address
        if set(address) not in (ADDRESS_FIELDS, ADDRESS_FIELDS | {"review_capacity"}):
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
        if "review_capacity" in address:
            capacity = address["review_capacity"]
            if not isinstance(capacity, Mapping) or set(capacity) != REVIEW_CAPACITY_FIELDS:
                raise AdapterError(
                    "OCRV_ADDRESS_INVALID",
                    "review_capacity must use the exact executing-limit field set",
                )
            _positive_integer(capacity["max_tokens"], "review_capacity.max_tokens")
            for field in ("max_tokens_budget", "timeout_minutes"):
                _nonnegative_integer(capacity[field], f"review_capacity.{field}")

    @staticmethod
    def _executing_capacity(address: Mapping[str, Any]) -> dict[str, int]:
        configured = address.get("review_capacity")
        if configured is None:
            return {field: int(DEFAULT_REVIEW_CAPACITY[field]) for field in REVIEW_CAPACITY_FIELDS}
        return {field: int(configured[field]) for field in REVIEW_CAPACITY_FIELDS}

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
        request_sha256 = canonical_json_sha256(payload)
        attempt.write_json_once(
            "started.json",
            make_native_start(
                adapter=endpoint.adapter,
                run_id=envelope.run_id,
                cell_id=envelope.cell_id,
                message_id=envelope.message_id,
                request_sha256=request_sha256,
                native_request_sha256=request_sha256,
                native_task_kind="checker-dispatch",
                native_task_id=f"dispatch:{envelope.message_id}",
                native_task_status="RUNNING",
                pid=os.getpid(),
            ),
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

    def _candidate_request(
        self,
        envelope: Envelope,
        review_capacity: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload = (
            envelope.payload["candidate_payload"]
            if envelope.payload_type == "D1_MANAGEMENT_RETURN"
            else envelope.payload
        )
        # Candidate/context fields are invocation inputs; extra report material is retained.
        repository = Path(_nonempty(payload["repository"], "repository"))
        if not repository.is_absolute() or not repository.is_dir():
            raise AdapterError("OCRV_PAYLOAD_INVALID", "repository must be an existing absolute directory")
        candidate = payload["candidate"]
        if not isinstance(candidate, Mapping):
            raise AdapterError("OCRV_PAYLOAD_INVALID", "candidate must be an object")
        if candidate.get("kind") == "commit":
            candidate = {"kind": "commit", "commit": candidate.get("commit")}
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
        scope = {
            "include_paths": [],
            "exclude_paths": [],
            "criterion_ids": [f"D1-{index:03d}" for index in range(1, len(criteria) + 1)],
        }
        scope["scope_sha256"] = canonical_json_sha256(scope)
        capacity = dict(DEFAULT_REVIEW_CAPACITY)
        if review_capacity is not None:
            capacity.update({field: int(review_capacity[field]) for field in REVIEW_CAPACITY_FIELDS})
        request = {
            "schema_version": "slk.ocrv-d1-request/v2",
            "run_id": envelope.run_id,
            "cell_id": envelope.cell_id,
            "repository": str(repository.resolve()),
            "candidate": dict(candidate),
            "cell_goal": _nonempty(payload["cell_goal"], "cell_goal"),
            "d1_criteria": [item.strip() for item in criteria],
            "evidence_files": list(evidence_files),
            "review_scope": scope,
            "capacity": capacity,
        }
        if envelope.payload_type == "D1_MANAGEMENT_RETURN":
            context = {key: envelope.payload[key] for key in (
                "management_action", "management_summary", "management_evidence_refs")}
            refs = context["management_evidence_refs"]
            if not isinstance(refs, list):
                raise AdapterError("OCRV_PAYLOAD_INVALID", "management evidence must be an array")
            for ref in refs:
                path = ref.get("path") if isinstance(ref, Mapping) else ref
                if not isinstance(path, str) or not Path(path).is_absolute() or not Path(path).is_file():
                    raise AdapterError("OCRV_PAYLOAD_INVALID", "management evidence must name existing absolute files")
                if path not in request["evidence_files"]:
                    request["evidence_files"].append(path)
            request["management_context"] = context
        return request

    def _read_ocrv_result(self, path: Path, request_path: Path, envelope: Envelope,
                          process_exit_code: int) -> Any:
        """Read output, not an engineering approval. The request owns its identity."""
        if not path.is_file():
            return None
        text = path.read_text(encoding="utf-8-sig", errors="replace")
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return text

    def validate_existing_result(
        self,
        path: Path,
        request_path: Path,
        envelope: Envelope,
        process_exit_code: int,
    ) -> Mapping[str, Any]:
        """Read preserved output without reviewing its engineering contents."""

        return self._read_ocrv_result(path, request_path, envelope, process_exit_code)

    def _review(self, endpoint: Endpoint, envelope: Envelope, attempt: Attempt) -> DeliveryResult:
        """One native Checker invocation. No host segmentation or synthesized verdict."""
        request = self._candidate_request(envelope, self._executing_capacity(endpoint.address))
        environment = os.environ.copy()
        environment.pop("SLK_ROLE_CREDENTIAL", None)
        environment.pop("SLK_OVERWATCHER_CREDENTIAL", None)
        environment["OCRV_SLK_RUNTIME_ROOT"] = str(endpoint.address["runtime_root"])
        request_path = attempt.write_json_once("ocrv-request.json", request)
        result_path = attempt.root / "ocrv-result.json"
        child_start_path = attempt.root / "native-start.received.json"
        digest = hashlib.sha256(request_path.read_bytes()).hexdigest()
        _arm_child_start(environment, child_start_path, endpoint, envelope, digest)
        command = _string_array(endpoint.address["command"], "command")
        command.extend(["--request", str(request_path), "--output", str(result_path)])
        process = spawn(command, cwd=str(request["repository"]), env=environment,
                        process_kwargs=_checker_process_kwargs())
        child_start = None
        start_error = None
        try:
            child_start = _await_native_start(process, child_start_path, endpoint, envelope,
                                             digest, _positive_seconds(endpoint.address["timeout_seconds"]))
            attempt.write_json_once("started.json", child_start)
        except AdapterError as exc:
            # A missing start is a communication fact; still collect everything produced.
            start_error = exc.error_code
        completed = finish(process, None)
        attempt.write_text_once("native.stdout.txt", completed.stdout)
        attempt.write_text_once("native.stderr.txt", completed.stderr)
        result = self._read_ocrv_result(result_path, request_path, envelope, completed.returncode)
        if isinstance(result, Mapping):
            artifacts = result.get("artifacts")
            raw = artifacts.get("raw_review") if isinstance(artifacts, Mapping) else None
            if isinstance(raw, str):
                raw_path = Path(raw).resolve()
                if (raw_path.is_relative_to(Path(endpoint.address["runtime_root"]).resolve())
                    and raw_path.name == "ocrv-review.json" and raw_path.is_file()
                    and not (attempt.root / "ocrv-review.json").exists()):
                    attempt.write_bytes_once("ocrv-review.json", raw_path.read_bytes())
        return DeliveryResult(RESULT_SCHEMA, envelope.message_id, envelope.run_id,
            endpoint.adapter, "completed" if completed.returncode == 0 and child_start else "failed",
            {"exit_code": completed.returncode, "run_id": envelope.run_id, "cell_id": envelope.cell_id,
             "native_started": child_start is not None,
             "review_invocation_id": child_start["native_task"]["id"] if child_start else None},
            start_error or (None if completed.returncode == 0 else "OCRV_EXIT_NONZERO"),
            tuple(name for name in ("started.json", "ocrv-request.json", "ocrv-result.json",
                "ocrv-review.json", "native.stdout.txt", "native.stderr.txt") if (attempt.root / name).is_file()))

    def deliver(self, endpoint: Endpoint, envelope: Envelope, attempt: Attempt) -> DeliveryResult:
        self.validate_address(endpoint)
        if envelope.payload_type == "CELL_DISPATCH":
            return self._dispatch(endpoint, envelope, attempt)
        if envelope.payload_type in {"CANDIDATE_READY", "D1_MANAGEMENT_RETURN"}:
            try:
                return self._review(endpoint, envelope, attempt)
            except (AdapterError, KeyError, TypeError, ValueError) as exc:
                code = getattr(exc, "error_code", "OCRV_INVOCATION_INPUT_UNAVAILABLE")
                attempt.write_json_once("checker-receipt.json", {
                    "native_started": (attempt.root / "started.json").is_file(),
                    "error_code": code, "input_report": dict(envelope.payload),
                })
                return DeliveryResult(RESULT_SCHEMA, envelope.message_id, envelope.run_id,
                    endpoint.adapter, "failed", {}, code, ("checker-receipt.json",))
        if envelope.payload_type == "WORKER_REPORT":
            attempt.write_json_once("checker-receipt.json", {
                "native_started": False, "error_code": "OCRV_CANDIDATE_NOT_PROVIDED",
                "input_report": dict(envelope.payload),
            })
            return DeliveryResult(RESULT_SCHEMA, envelope.message_id, envelope.run_id,
                endpoint.adapter, "failed", {}, "OCRV_CANDIDATE_NOT_PROVIDED", ("checker-receipt.json",))
        if envelope.payload_type in {"WORKER_COMPLETION_RECOVERY", "PRE_D0_BLOCKED_RECOVERY"}:
            attempt.write_json_once("checker-receipt.json", {
                "native_started": False, "error_code": "OUTPUT_FORMAT_RECOVERY_RETIRED",
                "input_report": dict(envelope.payload),
            })
            return DeliveryResult(RESULT_SCHEMA, envelope.message_id, envelope.run_id,
                endpoint.adapter, "failed", {}, "OUTPUT_FORMAT_RECOVERY_RETIRED", ("checker-receipt.json",))
        raise AdapterError("OCRV_PAYLOAD_UNSUPPORTED", "OCRV Checker payload type is unsupported")
