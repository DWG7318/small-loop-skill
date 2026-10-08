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
from .. import context_review
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
        scope = {
            "include_paths": [],
            "exclude_paths": [],
            "criterion_ids": [f"D1-{index:03d}" for index in range(1, len(criteria) + 1)],
        }
        scope["scope_sha256"] = canonical_json_sha256(scope)
        capacity = dict(DEFAULT_REVIEW_CAPACITY)
        if review_capacity is not None:
            capacity.update({field: int(review_capacity[field]) for field in REVIEW_CAPACITY_FIELDS})
        return {
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
        if isinstance(review["exit_code"], bool) or not isinstance(review["exit_code"], int):
            raise AdapterError("OCRV_RESULT_INVALID", "OCRV nested review exit code is invalid")
        return value

    def validate_existing_result(
        self,
        path: Path,
        request_path: Path,
        envelope: Envelope,
        process_exit_code: int,
    ) -> Mapping[str, Any]:
        """Reuse the ordinary OCRV closed-result validator for preserved evidence."""

        return self._read_ocrv_result(path, request_path, envelope, process_exit_code)

    def _review_segments(
        self,
        request: Mapping[str, Any],
        selected_paths: list[str],
        inventory: list[Mapping[str, Any]],
    ) -> list[dict[str, Any]]:
        criteria = list(request["d1_criteria"])
        capacity = request["capacity"]
        max_paths = int(capacity["max_segment_paths"])
        max_lines = int(capacity["max_changed_lines"])
        line_counts = {
            str(item.get("path")): int(item.get("insertions", 0)) + int(item.get("deletions", 0))
            for item in inventory
            if isinstance(item, Mapping) and isinstance(item.get("path"), str)
        }
        path_groups: list[list[str]] = []
        current: list[str] = []
        current_lines = 0
        for path in selected_paths:
            lines = line_counts.get(path, 0)
            if current and (len(current) >= max_paths or current_lines + lines > max_lines):
                path_groups.append(current)
                current = []
                current_lines = 0
            current.append(path)
            current_lines += lines
        if current:
            path_groups.append(current)
        criterion_ids = [f"D1-{ordinal:03d}" for ordinal in range(1, len(criteria) + 1)]
        segment_count = len(path_groups)
        segments: list[dict[str, Any]] = []
        for ordinal, scoped_paths in enumerate(path_groups, start=1):
            segments.append(
                self._make_review_segment(
                    request,
                    selected_paths,
                    scoped_paths,
                    criteria,
                    criterion_ids,
                    f"{ordinal}/{segment_count}",
                )
            )
        return segments

    @staticmethod
    def _make_review_segment(
        base_request: Mapping[str, Any],
        selected_paths: list[str],
        scoped_paths: list[str],
        scoped_criteria: list[str],
        criterion_ids: list[str],
        label: str,
    ) -> dict[str, Any]:
        scope = {
            "include_paths": scoped_paths,
            "exclude_paths": [path for path in selected_paths if path not in scoped_paths],
            "criterion_ids": criterion_ids,
        }
        scope["scope_sha256"] = canonical_json_sha256(scope)
        return {
            **base_request,
            "cell_goal": (
                f"[SLK review segment {label}] Changed-path scope: {', '.join(scoped_paths)}. "
                f"Original goal: {base_request['cell_goal']}"
            ),
            "d1_criteria": scoped_criteria,
            "review_scope": scope,
        }

    def _split_review_segment(
        self,
        base_request: Mapping[str, Any],
        selected_paths: list[str],
        segment: Mapping[str, Any],
    ) -> list[dict[str, Any]]:
        scoped_paths = list(segment["review_scope"]["include_paths"])
        scoped_criteria = list(segment["d1_criteria"])
        criterion_ids = list(segment["review_scope"]["criterion_ids"])
        if len(scoped_paths) > 1:
            midpoint = (len(scoped_paths) + 1) // 2
            parts = (scoped_paths[:midpoint], scoped_paths[midpoint:])
            return [
                self._make_review_segment(
                    base_request,
                    selected_paths,
                    part,
                    scoped_criteria,
                    criterion_ids,
                    "refined",
                )
                for part in parts
            ]
        if len(scoped_criteria) > 1:
            midpoint = (len(scoped_criteria) + 1) // 2
            return [
                self._make_review_segment(
                    base_request,
                    selected_paths,
                    scoped_paths,
                    criteria_part,
                    ids_part,
                    "refined",
                )
                for criteria_part, ids_part in (
                    (scoped_criteria[:midpoint], criterion_ids[:midpoint]),
                    (scoped_criteria[midpoint:], criterion_ids[midpoint:]),
                )
            ]
        return []

    def _read_preflight(
        self,
        path: Path,
        request_path: Path,
        envelope: Envelope,
    ) -> Mapping[str, Any]:
        try:
            value = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError) as exc:
            raise AdapterError("OCRV_PREFLIGHT_INVALID", "OCRV preflight is missing or invalid") from exc
        if not isinstance(value, dict) or set(value) != OCRV_PREFLIGHT_FIELDS:
            raise AdapterError("OCRV_PREFLIGHT_INVALID", "OCRV preflight is not closed")
        if (
            value["schema_version"] != "slk.ocrv-d1-preflight/v1"
            or value["status"] not in {"READY", "INCOMPLETE"}
            or value["run_id"] != envelope.run_id
            or value["cell_id"] != envelope.cell_id
            or value["request_sha256"] != hashlib.sha256(request_path.read_bytes()).hexdigest()
        ):
            raise AdapterError("OCRV_PREFLIGHT_INVALID", "OCRV preflight identity mismatch")
        background = value["background"]
        preview = value["preview"]
        if not isinstance(background, dict) or set(background) != OCRV_PREFLIGHT_BACKGROUND_FIELDS:
            raise AdapterError("OCRV_PREFLIGHT_INVALID", "OCRV preflight background is invalid")
        if not isinstance(preview, dict) or set(preview) != OCRV_PREFLIGHT_PREVIEW_FIELDS:
            raise AdapterError("OCRV_PREFLIGHT_INVALID", "OCRV preview is invalid")
        if not all(
            isinstance(background[name], int) and not isinstance(background[name], bool) and background[name] >= 0
            for name in ("characters", "bytes", "evidence_bytes")
        ):
            raise AdapterError("OCRV_PREFLIGHT_INVALID", "OCRV background metrics are invalid")
        selected = preview["selected_paths"]
        if not isinstance(selected, list) or not all(isinstance(item, str) and item for item in selected):
            raise AdapterError("OCRV_PREFLIGHT_INVALID", "OCRV preview selected paths are invalid")
        if len(selected) != len(set(selected)) or not isinstance(preview["inventory"], list):
            raise AdapterError("OCRV_PREFLIGHT_INVALID", "OCRV preview inventory is invalid")
        return value

    def _run_preflight(
        self,
        endpoint: Endpoint,
        envelope: Envelope,
        request_path: Path,
        output_path: Path,
        environment: Mapping[str, str],
        timeout: float,
    ) -> tuple[Mapping[str, Any], subprocess.CompletedProcess[str]]:
        command = _string_array(endpoint.address["command"], "command")
        command.extend(["--preflight", "--request", str(request_path), "--output", str(output_path)])
        process = spawn(
            command,
            cwd=str(json.loads(request_path.read_text(encoding="utf-8"))["repository"]),
            env=dict(environment),
            process_kwargs=_checker_process_kwargs(),
        )
        completed = finish(process, timeout)
        if completed.returncode not in {0, 3}:
            raise AdapterError("OCRV_PREFLIGHT_INVALID", "OCRV preflight process failed")
        result = self._read_preflight(output_path, request_path, envelope)
        expected_status = "READY" if completed.returncode == 0 else "INCOMPLETE"
        if result["status"] != expected_status:
            raise AdapterError("OCRV_PREFLIGHT_INVALID", "OCRV preflight status and exit code disagree")
        return result, completed

    @staticmethod
    def _preflight_fits(request: Mapping[str, Any], preflight: Mapping[str, Any]) -> bool:
        preview = preflight["preview"]
        selected = set(preview["selected_paths"])
        inventoried: set[str] = set()
        for item in preview["inventory"]:
            if not isinstance(item, Mapping) or item.get("path") not in selected:
                continue
            path = str(item["path"])
            insertions = item.get("insertions", 0)
            deletions = item.get("deletions", 0)
            if any(isinstance(value, bool) or not isinstance(value, int) or value < 0 for value in (insertions, deletions)):
                return False
            inventoried.add(path)
        return bool(
            preflight["status"] == "READY"
            and inventoried == selected
        )

    @staticmethod
    def _has_blocking_finding(result: Mapping[str, Any]) -> bool:
        for finding in result["findings"]:
            if not isinstance(finding, Mapping):
                continue
            severity = str(finding.get("severity", finding.get("priority", ""))).upper()
            if severity in {"HIGH", "BLOCKER", "CRITICAL"} or finding.get("blocking") is True:
                return True
        return False

    def _recovery_request(
        self,
        endpoint: Endpoint,
        envelope: Envelope,
        recovery_invocation_id: str,
        result_path: Path,
    ) -> dict[str, Any]:
        payload = envelope.payload
        pre_d0 = envelope.payload_type == "PRE_D0_BLOCKED_RECOVERY"
        _closed(
            payload,
            PRE_D0_RECOVERY_FIELDS if pre_d0 else RECOVERY_FIELDS,
            f"{envelope.payload_type} payload",
        )
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
        projection = json.loads(Path(paths["runtime_projection_path"]).read_text(encoding="utf-8-sig"))
        version = projection.get("summary", {}).get("slk_version")
        if version not in SUPPORTED_METHOD_VERSIONS or projection.get("runtime_snapshot", {}).get("method_version") != version:
            raise AdapterError("OCRV_PAYLOAD_INVALID", "recovery Run version is unsupported or inconsistent")
        request = {
            "schema_version": "slk.ocrv-worker-recovery-request/v1",
            "method_version": version,
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
        if pre_d0:
            environment_path = Path(_nonempty(payload["environment_adjustment_path"], "environment_adjustment_path"))
            digest = _nonempty(payload["environment_adjustment_sha256"], "environment_adjustment_sha256")
            if (
                not environment_path.is_absolute()
                or not environment_path.is_file()
                or len(digest) != 64
                or any(character not in "0123456789abcdef" for character in digest)
            ):
                raise AdapterError(
                    "OCRV_PAYLOAD_INVALID",
                    "pre-D0 environment adjustment must be an existing absolute SHA-bound file",
                )
            request.update(
                {
                    "environment_adjustment_path": str(environment_path.resolve()),
                    "environment_adjustment_sha256": digest,
                }
            )
        return request

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
            or value["method_version"] != json.loads(request_path.read_text(encoding="utf-8-sig"))["method_version"]
            or value["status"] != "CHECKER_D1_RECORDED"
            or value["run_id"] != envelope.run_id
            or value["cell_id"] != envelope.cell_id
            or value["checker_role_instance_id"] != endpoint.role_instance_id
            or value["checker_endpoint_version"] != endpoint.endpoint_version
            or value["checker_authenticated"] is not True
            or value["authorized_recovery"] is not True
            or value["recovery_invocation_id"] != recovery_invocation_id
            or value["request_sha256"] != hashlib.sha256(request_path.read_bytes()).hexdigest()
            or isinstance(value["runtime_revision"], bool)
            or not isinstance(value["runtime_revision"], int)
            or value["runtime_revision"] < 1
            or isinstance(value["token_sequence"], bool)
            or not isinstance(value["token_sequence"], int)
            or value["token_sequence"] < 1
            or not isinstance(value["checker_token_already_committed"], bool)
            or not isinstance(value["native_attempt_path"], str)
            or not Path(value["native_attempt_path"]).is_absolute()
            or value["d1_verdict"] not in {"PASS", "FAIL", "INCOMPLETE"}
            or value["d1_event_type"]
            != {"PASS": "D1_PASSED", "FAIL": "D1_FAILED", "INCOMPLETE": "D1_INCOMPLETE"}[
                value["d1_verdict"]
            ]
            or not isinstance(value["native_result_path"], (str, type(None)))
            or (
                isinstance(value["native_result_path"], str)
                and not Path(value["native_result_path"]).is_absolute()
            )
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
        environment.pop("SLK_TRANSPORT_ROLE_HOST", None)
        environment.pop("SLK_TRANSPORT_ROLE_HOST_SHA256", None)
        environment["SLK_OCRV_RECOVERY_ROLE_INSTANCE_ID"] = endpoint.role_instance_id
        environment["SLK_OCRV_RECOVERY_INVOCATION_ID"] = recovery_invocation_id
        environment["SLK_OCRV_RECOVERY_ENDPOINT_VERSION"] = str(endpoint.endpoint_version)
        recovery_request_sha256 = hashlib.sha256(request_path.read_bytes()).hexdigest()
        child_start_path = attempt.root / "native-start.received.json"
        _arm_child_start(
            environment,
            child_start_path,
            endpoint,
            envelope,
            recovery_request_sha256,
        )
        process = spawn(
            command,
            cwd=str(Path(endpoint.address["runtime_root"])),
            env=environment,
            process_kwargs=_checker_process_kwargs(),
        )
        child_start = _await_native_start(
            process,
            child_start_path,
            endpoint,
            envelope,
            recovery_request_sha256,
            _positive_seconds(endpoint.address["timeout_seconds"]),
        )
        attempt.write_json_once(
            "started.json",
            child_start,
        )
        try:
            completed = finish(process, None)
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
                "runtime_revision": result["runtime_revision"],
                "token_sequence": result["token_sequence"],
                "checker_token_already_committed": result["checker_token_already_committed"],
                "native_attempt_path": result["native_attempt_path"],
                "d1_verdict": result["d1_verdict"],
                "d1_event_type": result["d1_event_type"],
                "native_result_path": result["native_result_path"],
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
        request = self._candidate_request(
            envelope,
            None
            if envelope.payload_type == "D1_MANAGEMENT_RETURN"
            else self._executing_capacity(endpoint.address),
        )
        context = None
        if envelope.payload_type == "D1_MANAGEMENT_RETURN":
            for source in envelope.payload["management_evidence_refs"]:
                path = Path(source)
                if not path.is_absolute() or not path.is_file():
                    raise AdapterError("OCRV_CONTEXT_RECOVERY_INVALID", "context management source is unavailable")
                try:
                    plan = context_review.read(path)
                except (OSError, ValueError) as exc:
                    if path.suffix.lower() == ".json":
                        raise AdapterError("OCRV_CONTEXT_RECOVERY_INVALID", "context management JSON source is invalid") from exc
                    continue  # Other management evidence may be Markdown, not a recovery plan.
                if plan.get("schema_version") not in context_review.SCHEMAS:
                    if str(plan.get("schema_version", "")).startswith("slk.ocrv-context-recovery-plan/"):
                        raise AdapterError("OCRV_CONTEXT_RECOVERY_INVALID", "context plan schema version is unsupported")
                    continue
                try:
                    if context is not None:
                        raise ValueError("duplicate context recovery plans")
                    if plan["schema_version"] == context_review.THRESHOLD_SCHEMA:
                        # Keep the original per-call ceiling; management defaults must not upgrade it.
                        frozen = context_review.read(Path(plan["sources"]["request"]["path"]))
                        request = {**request, "capacity": frozen["capacity"]}
                    context = context_review.validate(plan, request, envelope.payload)
                    context.update(plan=plan, plan_path=path, plan_sha256=context_review.digest(path))
                except (OSError, ValueError, KeyError, TypeError) as exc:
                    raise AdapterError("OCRV_CONTEXT_RECOVERY_INVALID", str(exc)) from exc
            if context is not None:
                attempt.write_json_once("ocrv-context-recovery-plan.json", context["plan"])
        environment = os.environ.copy()
        environment.pop("SLK_ROLE_CREDENTIAL", None)
        environment.pop("SLK_OVERWATCHER_CREDENTIAL", None)
        environment["OCRV_SLK_RUNTIME_ROOT"] = str(endpoint.address["runtime_root"])
        timeout = _positive_seconds(endpoint.address["timeout_seconds"])

        def incomplete(
            planned: int = 0,
            completed_count: int = 0,
            evidence: tuple[str, ...] = (),
        ) -> DeliveryResult:
            return DeliveryResult(
                RESULT_SCHEMA,
                envelope.message_id,
                envelope.run_id,
                endpoint.adapter,
                "failed",
                {
                    "run_id": envelope.run_id,
                    "cell_id": envelope.cell_id,
                    "review_segment_count": planned,
                    "completed_review_segments": completed_count,
                },
                "OCRV_REVIEW_INCOMPLETE",
                evidence,
            )

        preflight_request_path = attempt.write_json_once("ocrv-preflight-request.json", request)
        preflight_path = attempt.root / "ocrv-preflight.json"
        try:
            preflight, preflight_process = self._run_preflight(
                endpoint,
                envelope,
                preflight_request_path,
                preflight_path,
                environment,
                timeout,
            )
        except subprocess.TimeoutExpired as exc:
            attempt.write_text_once(
                "ocrv-preflight.stderr.txt",
                exc.stderr if isinstance(exc.stderr, str) else "",
            )
            return incomplete(evidence=("ocrv-preflight-request.json",))
        attempt.write_text_once("ocrv-preflight.stdout.txt", preflight_process.stdout)
        attempt.write_text_once("ocrv-preflight.stderr.txt", preflight_process.stderr)
        preview = preflight["preview"]
        selected_paths = list(preview["selected_paths"])
        segments = []
        if context is not None:
            if set(selected_paths) != set(context["selected"]):
                raise AdapterError("OCRV_CONTEXT_RECOVERY_INVALID", "context source scope changed in current preview")
            segments = [self._make_review_segment(
                request, selected_paths, group, list(request["d1_criteria"]),
                list(request["review_scope"]["criterion_ids"]), f"{i}/{len(context['groups'])}",
            ) for i, group in enumerate(context["groups"], 1)]
        if not self._preflight_fits(request, preflight):
            return incomplete(
                evidence=("ocrv-preflight-request.json", "ocrv-preflight.json")
            )
        if not segments:
            request_path = attempt.write_json_once("ocrv-request.json", request)
            result_path = attempt.root / "ocrv-result.json"
            command = _string_array(endpoint.address["command"], "command")
            command.extend(["--request", str(request_path), "--output", str(result_path)])
            request_sha256 = hashlib.sha256(request_path.read_bytes()).hexdigest()
            child_start_path = attempt.root / "native-start.received.json"
            _arm_child_start(
                environment,
                child_start_path,
                endpoint,
                envelope,
                request_sha256,
            )
            try:
                process = spawn(
                    command,
                    cwd=str(request["repository"]),
                    env=environment,
                    process_kwargs=_checker_process_kwargs(),
                )
                child_start = _await_native_start(
                    process,
                    child_start_path,
                    endpoint,
                    envelope,
                    request_sha256,
                    timeout,
                )
                attempt.write_json_once("started.json", child_start)
                completed = finish(process, None)
            except subprocess.TimeoutExpired as exc:
                attempt.write_text_once(
                    "native.stdout.txt", exc.stdout if isinstance(exc.stdout, str) else ""
                )
                attempt.write_text_once(
                    "native.stderr.txt", exc.stderr if isinstance(exc.stderr, str) else ""
                )
                raise AdapterError("OCRV_TIMEOUT", "OCRV Checker did not complete in time") from exc
            attempt.write_text_once("native.stdout.txt", completed.stdout)
            attempt.write_text_once("native.stderr.txt", completed.stderr)
            result = self._read_ocrv_result(
                result_path, request_path, envelope, completed.returncode
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
                    "review_segment_count": 0,
                },
                error_code=None,
                evidence=(
                    "started.json",
                    "ocrv-preflight.json",
                    "ocrv-request.json",
                    "ocrv-result.json",
                    "native.stdout.txt",
                    "native.stderr.txt",
                ),
            )

        fitted_segments: list[
            tuple[dict[str, Any], Mapping[str, Any], subprocess.CompletedProcess[str]]
        ] = []
        pending_segments = list(segments)
        proposal_ordinal = 0
        while pending_segments:
            segment_request = pending_segments.pop(0)
            proposal_ordinal += 1
            proposal_root = (
                attempt.root
                / "review-preflight-proposals"
                / f"proposal-{proposal_ordinal:03d}"
            )
            proposal_root.mkdir(parents=True, exist_ok=False)
            proposal_attempt = Attempt(proposal_root)
            proposal_request_path = proposal_attempt.write_json_once(
                "request.json", segment_request
            )
            proposal_preflight_path = proposal_root / "preflight.json"
            try:
                proposal_preflight, proposal_process = self._run_preflight(
                    endpoint,
                    envelope,
                    proposal_request_path,
                    proposal_preflight_path,
                    environment,
                    timeout,
                )
            except (subprocess.TimeoutExpired, AdapterError):
                return incomplete(
                    len(segments), 0, ("ocrv-preflight.json",)
                )
            proposal_attempt.write_text_once("preflight.stdout.txt", proposal_process.stdout)
            proposal_attempt.write_text_once("preflight.stderr.txt", proposal_process.stderr)
            scope_matches = (
                proposal_preflight["preview"]["selected_paths"]
                == segment_request["review_scope"]["include_paths"]
            )
            if scope_matches and self._preflight_fits(segment_request, proposal_preflight):
                fitted_segments.append((segment_request, proposal_preflight, proposal_process))
                continue
            if context is not None and context["plan"]["schema_version"] == context_review.THRESHOLD_SCHEMA:
                return incomplete(len(segments), 0, ("ocrv-preflight.json",))
            refinements = (
                self._split_review_segment(request, selected_paths, segment_request)
                if scope_matches and proposal_preflight["preview"]["exit_code"] == 0
                else []
            )
            if not refinements:
                return incomplete(
                    len(segments), 0, ("ocrv-preflight.json",)
                )
            pending_segments = refinements + pending_segments

        segments = [item[0] for item in fitted_segments]
        segment_results: list[tuple[Path, Mapping[str, Any], int]] = []
        stopped_on_blocker = False
        for ordinal, (
            segment_request,
            segment_preflight,
            segment_preflight_process,
        ) in enumerate(fitted_segments, start=1):
            segment_root = attempt.root / "review-segments" / f"segment-{ordinal:03d}"
            segment_root.mkdir(parents=True, exist_ok=False)
            segment_attempt = Attempt(segment_root)
            segment_request_path = segment_attempt.write_json_once("request.json", segment_request)
            segment_attempt.write_json_once("preflight.json", segment_preflight)
            segment_attempt.write_text_once("preflight.stdout.txt", segment_preflight_process.stdout)
            segment_attempt.write_text_once("preflight.stderr.txt", segment_preflight_process.stderr)
            segment_result_path = segment_root / "result.json"
            command = _string_array(endpoint.address["command"], "command")
            command.extend(["--request", str(segment_request_path), "--output", str(segment_result_path)])
            first_segment = not (attempt.root / "started.json").is_file()
            segment_sha256 = hashlib.sha256(segment_request_path.read_bytes()).hexdigest()
            child_start_path = (
                attempt.root / "native-start.received.json"
                if first_segment
                else segment_root / "started.json"
            )
            _arm_child_start(
                environment,
                child_start_path,
                endpoint,
                envelope,
                segment_sha256,
            )
            process = spawn(
                command,
                cwd=str(request["repository"]),
                env=environment,
                process_kwargs=_checker_process_kwargs(),
            )
            child_start = _await_native_start(
                process,
                child_start_path,
                endpoint,
                envelope,
                segment_sha256,
                timeout,
            )
            if first_segment:
                attempt.write_json_once("started.json", child_start)
            try:
                completed = finish(process, None)
            except subprocess.TimeoutExpired as exc:
                segment_attempt.write_text_once(
                    "native.stdout.txt", exc.stdout if isinstance(exc.stdout, str) else ""
                )
                segment_attempt.write_text_once(
                    "native.stderr.txt", exc.stderr if isinstance(exc.stderr, str) else ""
                )
                attempt.write_json_once(
                    "ocrv-review-progress.json",
                    {
                        "schema_version": "slk.ocrv-review-progress/v1",
                        "run_id": envelope.run_id,
                        "cell_id": envelope.cell_id,
                        "status": "INCOMPLETE",
                        "completed_segments": len(segment_results),
                        "total_segments": len(segments),
                        "current_segment": ordinal,
                    },
                )
                return incomplete(
                    len(segments),
                    len(segment_results),
                    ("started.json", "ocrv-review-progress.json"),
                )
            segment_attempt.write_text_once("native.stdout.txt", completed.stdout)
            segment_attempt.write_text_once("native.stderr.txt", completed.stderr)
            segment_result = self._read_ocrv_result(
                segment_result_path, segment_request_path, envelope, completed.returncode
            )
            if context is not None:
                try:
                    context_review.validate_segment(context, segment_result, segment_request["review_scope"]["include_paths"])
                except (OSError, ValueError, KeyError, TypeError) as exc:
                    raise AdapterError("OCRV_CONTEXT_RECOVERY_INVALID", str(exc)) from exc
            segment_results.append((segment_result_path, segment_result, completed.returncode))
            segment_review = segment_result["review"]
            attempt.write_json_once(
                f"ocrv-review-progress-{ordinal:03d}.json",
                {
                    "schema_version": "slk.ocrv-review-progress/v1",
                    "run_id": envelope.run_id,
                    "cell_id": envelope.cell_id,
                    "status": "SEGMENT_COMPLETE",
                    "completed_segments": len(segment_results),
                    "total_segments": len(segments),
                    "current_segment": ordinal,
                    "request_sha256": hashlib.sha256(segment_request_path.read_bytes()).hexdigest(),
                    "result_sha256": hashlib.sha256(segment_result_path.read_bytes()).hexdigest(),
                    "review_invocation_id": segment_result["review_invocation_id"],
                    "session_id": segment_review["session_id"],
                    "process_exit_code": completed.returncode,
                },
            )
            if segment_result["verdict"] == "INCOMPLETE":
                if context is not None:
                    break  # Preserve this native terminal and publish a truthful full-scope INCOMPLETE.
                return incomplete(
                    len(segments), len(segment_results), ("started.json",)
                )
            if self._has_blocking_finding(segment_result):
                stopped_on_blocker = True
                break

        verdict = (
            "INCOMPLETE" if any(item[1]["verdict"] == "INCOMPLETE" for item in segment_results)
            else "FAIL" if any(item[1]["verdict"] == "FAIL" for item in segment_results) else "PASS"
        )
        reason_codes: list[str] = []
        compact_segments: list[dict[str, Any]] = []
        compact_findings: list[dict[str, Any]] = []
        for ordinal, (path, value, _exit_code) in enumerate(segment_results, start=1):
            for code in value["reason_codes"]:
                if code not in reason_codes:
                    reason_codes.append(code)
            for finding in value["findings"]:
                encoded = json.dumps(finding, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                compact_findings.append(dict(finding) if context is not None else
                    {
                        "severity": str(finding.get("severity", "UNKNOWN")) if isinstance(finding, Mapping) else "UNKNOWN",
                        "finding_sha256": hashlib.sha256(encoded.encode("utf-8")).hexdigest(),
                    }
                )
            compact_segments.append(
                {
                    "ordinal": ordinal,
                    "request_sha256": value["request_sha256"],
                    "result_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                    "verdict": value["verdict"],
                    "reason_codes": list(value["reason_codes"]),
                    "review_invocation_id": value["review_invocation_id"],
                    "session_id": value["review"]["session_id"],
                }
            )
        if context is not None:
            # Recheck all frozen source bytes before a formal result, not merely before dispatch.
            try:
                if context_review.digest(context["plan_path"]) != context["plan_sha256"]:
                    raise ValueError("context recovery plan changed during review")
                context_review.validate(context["plan"], request, envelope.payload)
            except (OSError, ValueError, KeyError, TypeError) as exc:
                raise AdapterError("OCRV_CONTEXT_RECOVERY_INVALID", str(exc)) from exc
            compact_findings[:0] = [{k: v for k, v in x.items() if k not in {"thinking", "reasoning", "analysis"}}
                                   for x in context["raw"]["comments"]]
            if verdict != "INCOMPLETE" and any(str(x.get("severity", "")).upper()
                    in {"MEDIUM", "HIGH", "BLOCKER", "CRITICAL"} for x in compact_findings):
                verdict = "FAIL"
        aggregate = {
            "schema_version": "slk.ocrv-d1-aggregate/v1",
            "run_id": envelope.run_id,
            "cell_id": envelope.cell_id,
            "verdict": verdict,
            "reason_codes": reason_codes,
            "planned_segment_count": len(segments),
            "completed_segment_count": len(segment_results),
            "stopped_on_blocking_finding": stopped_on_blocker,
            "segments": compact_segments,
            "findings": compact_findings,
        }
        if context is not None:
            aggregate["context_recovery"] = {
                "plan_sha256": context["plan_sha256"], "sources": context["plan"]["sources"],
                "parent_session_id": context["raw"]["session_id"], "reused": context["reused"],
                "selected": list(context["selected"].values()),
            }
            if context["plan"]["schema_version"] == context_review.THRESHOLD_SCHEMA:
                settled = len(segment_results) - int(verdict == "INCOMPLETE")
                aggregate["context_recovery"].update(failure_kind=context_review.THRESHOLD_KIND,
                    reviewed_paths=[p for group in context["groups"][:settled] for p in group],
                    not_reviewed_paths=[p for group in context["groups"][settled:] for p in group])
        aggregate_path = attempt.write_json_once("ocrv-aggregate.json", aggregate)
        final_scope = {
            "include_paths": list(preview["selected_paths"]),
            "exclude_paths": [],
            "criterion_ids": [f"D1-{index:03d}" for index in range(1, len(request["d1_criteria"]) + 1)],
        }
        final_scope["scope_sha256"] = canonical_json_sha256(final_scope)
        final_request = {**request, "review_scope": final_scope}
        request_path = attempt.write_json_once("ocrv-request.json", final_request)
        formal_exit_code = VERDICT_EXIT_CODES[verdict]
        result = {
            "schema_version": "slk.ocrv-d1-result/v1",
            "run_id": envelope.run_id,
            "cell_id": envelope.cell_id,
            "review_invocation_id": str(uuid.uuid4()),
            "verdict": verdict,
            "reason_codes": reason_codes,
            "findings": compact_findings,
            "review": {
                "status": "partial" if verdict == "INCOMPLETE" else "complete",
                "provider": EXPECTED_PROVIDER,
                "model": EXPECTED_MODEL,
                "session_id": f"ocrv-aggregate-{uuid.uuid4()}",
                "exit_code": formal_exit_code,
            },
            "evidence": [hashlib.sha256(aggregate_path.read_bytes()).hexdigest()],
            "request_sha256": hashlib.sha256(request_path.read_bytes()).hexdigest(),
            "artifacts": {"aggregate": "ocrv-aggregate.json"},
        }
        attempt.write_json_once("ocrv-result.json", result)
        attempt.write_json_once(
            "ocrv-review-progress.json",
            {
                "schema_version": "slk.ocrv-review-progress/v1",
                "run_id": envelope.run_id,
                "cell_id": envelope.cell_id,
                "status": "INCOMPLETE" if verdict == "INCOMPLETE" else "BLOCKED" if stopped_on_blocker else "COMPLETE",
                "completed_segments": len(segment_results),
                "total_segments": len(segments),
                "current_segment": len(segment_results),
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
                "session_id": result["review"]["session_id"],
                "provider": EXPECTED_PROVIDER,
                "model": EXPECTED_MODEL,
                "verdict": verdict,
                "exit_code": formal_exit_code,
                "review_segment_count": len(segment_results),
            },
            error_code=None,
            evidence=(
                "started.json",
                "ocrv-preflight.json",
                "ocrv-aggregate.json",
                "ocrv-request.json",
                "ocrv-result.json",
                "ocrv-review-progress.json",
            ),
        )

    def deliver(self, endpoint: Endpoint, envelope: Envelope, attempt: Attempt) -> DeliveryResult:
        self.validate_address(endpoint)
        if envelope.payload_type == "CELL_DISPATCH":
            return self._dispatch(endpoint, envelope, attempt)
        if envelope.payload_type in {"CANDIDATE_READY", "D1_MANAGEMENT_RETURN"}:
            return self._review(endpoint, envelope, attempt)
        if envelope.payload_type in {"WORKER_COMPLETION_RECOVERY", "PRE_D0_BLOCKED_RECOVERY"}:
            return self._recover(endpoint, envelope, attempt)
        raise AdapterError("OCRV_PAYLOAD_UNSUPPORTED", "OCRV Checker payload type is unsupported")
