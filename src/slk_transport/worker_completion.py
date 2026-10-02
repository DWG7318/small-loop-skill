"""Bounded Worker-completion continuation and read-only handoff inspection."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time
import uuid
import ctypes
from ctypes import wintypes
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

from .adapters.base import AdapterError
from .adapters.ocrv import OcrvAdapter, VERDICT_EXIT_CODES
from .contracts import (
    ENVELOPE_SCHEMA,
    ContractError,
    DeliveryResult,
    Endpoint,
    Envelope,
    canonical_json_sha256,
    parse_delivery,
)
from .native_activity import NativeActivityError, inspect_native_activity, validate_native_start
from .task_file import TaskFileError, verify_task_file


INSPECTION_SCHEMA = "slk.worker-completion-inspection/v1"
CONTINUATION_SCHEMA = "slk.worker-continuation/v1"
CHECKER_RECOVERY_SCHEMA = "slk.ocrv-worker-recovery-request/v1"
CHECKER_RECOVERY_RESULT_SCHEMA = "slk.ocrv-worker-recovery-result/v1"
COMMITTED_TERMINAL_SCHEMA = "slk.ocrv-committed-terminal-request/v1"
COMMITTED_TERMINAL_RESULT_SCHEMA = "slk.ocrv-committed-terminal-result/v1"
INCOMPLETE_RESUME_SCHEMA = "slk.ocrv-incomplete-checker-resume-request/v1"
COMMITTED_TERMINAL_RESULT_FIELDS = frozenset(
    {
        "schema_version", "method_version", "status", "run_id", "cell_id", "attempt",
        "candidate_message_id", "checker_role_instance_id", "checker_endpoint_version",
        "checker_authenticated", "authorized_existing_terminal", "recovery_invocation_id",
        "request_sha256", "runtime_revision", "token_sequence", "native_attempt_path",
        "d1_verdict", "d1_event_type", "native_result_path",
    }
)
_NAMESPACE = uuid.UUID("23c8316f-29fe-4f2f-b5c5-90ba4e7b1224")
_LEGACY_WORKER_START_FIELDS = frozenset(
    {"instance_id", "message_id", "run_id", "session_id", "status", "task_sha256"}
)
INVALID_SUPPLEMENT_RESULT_CONTRACT = {
    "worker_result_fields": [
        "schema_version",
        "message_id",
        "run_id",
        "role_instance_id",
        "status",
        "candidate",
        "next_payload",
    ],
    "next_payload_fields": [
        "attempt",
        "candidate_repository",
        "cell_id",
        "changed_paths",
        "d0",
        "suffix_blocker",
        "unproved",
    ],
    "d0_fields": [
        "baseline_commit",
        "branch",
        "candidate_commit",
        "changed_paths",
        "evidence_files",
        "focused_command",
        "frozen_command",
        "frozen_command_result",
        "green",
        "red",
        "unproved",
    ],
}
CONTINUATION_FIELDS = {
    "schema_version",
    "method_version",
    "run_id",
    "go_id",
    "cell_id",
    "attempt",
    "plan_revision",
    "runtime_revision",
    "source_message_id",
    "source_attempt_root",
    "continuation_result_path",
    "source_endpoint_sha256",
    "source_envelope_sha256",
    "source_runtime_projection_sha256",
    "source_runtime_snapshot",
    "recovery_mode",
    "worker_result_path",
    "worker_result_sha256",
    "source_terminal_sha256",
    "source_task_sha256",
    "source_started_sha256",
    "source_invalid_result_sha256",
    "source_candidate",
    "source_candidate_parent",
    "source_repository",
    "source_changed_paths",
    "supplement_result_contract",
    "worker_role_instance_id",
    "worker_instance_id",
    "worker_session_id",
    "checker_endpoint",
    "credential_path",
    "state_command",
    "transport_command",
    "token_sequence",
    "checker_token_already_committed",
    "occurred_at",
}


class CompletionError(ValueError):
    def __init__(self, error_code: str, message: str) -> None:
        super().__init__(message)
        self.error_code = error_code


def _read_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CompletionError("WORKER_COMPLETION_EVIDENCE_INVALID", f"{label} is unreadable") from exc
    if not isinstance(value, dict):
        raise CompletionError("WORKER_COMPLETION_EVIDENCE_INVALID", f"{label} must be an object")
    return value


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _timestamp(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise CompletionError("WORKER_COMPLETION_TIME_INVALID", "observed_at must be RFC3339") from exc
    if parsed.tzinfo is None:
        raise CompletionError("WORKER_COMPLETION_TIME_INVALID", "observed_at must include a timezone")
    return parsed.astimezone(timezone.utc)


def _file_timestamp(path: Path) -> datetime:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    except OSError as exc:
        raise CompletionError(
            "WORKER_COMPLETION_EVIDENCE_INVALID",
            "Worker terminal evidence timestamp is unavailable",
        ) from exc


def _stable_id(source_message_id: str, suffix: str) -> str:
    return str(uuid.uuid5(_NAMESPACE, f"{source_message_id}:{suffix}"))


def _write_or_reuse_stable_request(path: Path, value: Mapping[str, Any]) -> Path:
    """Keep the first immutable request bytes when an exact retry has a later clock value."""

    encoded = (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode(
        "utf-8"
    )
    if path.exists():
        existing_bytes = path.read_bytes()
        try:
            existing = json.loads(existing_bytes)
        except json.JSONDecodeError as exc:
            raise CompletionError("WORKER_CONTINUATION_CONFLICT", f"immutable request is invalid: {path.name}") from exc
        comparable = dict(value)
        if isinstance(existing, dict) and "occurred_at" in comparable:
            comparable["occurred_at"] = existing.get("occurred_at")
        if existing != comparable:
            raise CompletionError("WORKER_CONTINUATION_CONFLICT", f"immutable request conflicts: {path.name}")
        return path
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(encoded)
    temporary.replace(path)
    return path


def _event_details(value: Mapping[str, Any]) -> Mapping[str, Any] | None:
    details = value.get("details")
    if isinstance(details, Mapping):
        return details
    serialized = value.get("details_json")
    if isinstance(serialized, str):
        try:
            parsed = json.loads(serialized)
        except json.JSONDecodeError:
            return None
        return parsed if isinstance(parsed, Mapping) else None
    return None


def _source_attempt(runtime_projection: Mapping[str, Any], envelope: Envelope) -> int:
    events = runtime_projection.get("events")
    if not isinstance(events, list):
        raise CompletionError("WORKER_COMPLETION_ATTEMPT_UNPROVEN", "runtime events are unavailable")
    attempts: set[int] = set()
    for item in events:
        if (
            not isinstance(item, Mapping)
            or item.get("event_type") != "TRANSPORT_STARTED"
            or item.get("cell_id") != envelope.cell_id
        ):
            continue
        details = _event_details(item)
        attempt = item.get("attempt")
        if (
            details is not None
            and details.get("message_id") == envelope.message_id
            and isinstance(attempt, int)
            and not isinstance(attempt, bool)
            and attempt >= 1
        ):
            attempts.add(attempt)
    if len(attempts) != 1:
        raise CompletionError(
            "WORKER_COMPLETION_ATTEMPT_UNPROVEN",
            "source message must bind exactly one current TRANSPORT_STARTED attempt",
        )
    return attempts.pop()


def _missing_result_failure(attempt: Path, envelope: Envelope) -> dict[str, Any] | None:
    """Return the exact legacy DSH missing-result terminal, if present."""

    failed_path = attempt / "failed.json"
    if (
        not failed_path.is_file()
        or (attempt / "completed.json").exists()
        or (attempt / "worker-result.json").exists()
    ):
        return None
    failed = _read_object(failed_path, "Worker failed result")
    if (
        failed.get("schema_version") != "slk.transport-result/v1"
        or failed.get("message_id") != envelope.message_id
        or failed.get("run_id") != envelope.run_id
        or failed.get("adapter") != "dsh-worker"
        or failed.get("status") != "failed"
        or failed.get("error_code") != "DSH_RESULT_MISSING"
    ):
        return None
    return failed


def _git_text(repository: Path, *arguments: str) -> str:
    from .process import windows_no_window_kwargs

    completed = subprocess.run(
        ["git", *arguments],
        cwd=repository,
        text=True,
        encoding="utf-8",
        errors="strict",
        capture_output=True,
        check=False,
        **windows_no_window_kwargs(),
    )
    if completed.returncode != 0:
        raise CompletionError(
            "WORKER_CONTINUATION_NOT_READY",
            f"candidate repository cannot prove git {' '.join(arguments)}",
        )
    return completed.stdout.strip()


def _candidate_repository_snapshot(repository: Path) -> dict[str, Any]:
    repository = repository.resolve()
    if not repository.is_dir():
        raise CompletionError("WORKER_CONTINUATION_NOT_READY", "candidate repository is unavailable")
    root = Path(_git_text(repository, "rev-parse", "--show-toplevel")).resolve()
    if root != repository:
        raise CompletionError("WORKER_CONTINUATION_NOT_READY", "candidate repository root changed")
    status = _git_text(repository, "status", "--porcelain=v1", "--untracked-files=all")
    if status:
        raise CompletionError("WORKER_CONTINUATION_NOT_READY", "candidate repository is not clean")
    head = _git_text(repository, "rev-parse", "HEAD")
    parent = _git_text(repository, "rev-parse", "HEAD^")
    changed_paths = sorted(
        item for item in _git_text(repository, "diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD").splitlines()
        if item
    )
    if (
        len(head) != 40
        or len(parent) != 40
        or any(character not in "0123456789abcdef" for character in head + parent)
        or not changed_paths
    ):
        raise CompletionError("WORKER_CONTINUATION_NOT_READY", "candidate git identity is invalid")
    return {
        "repository": str(repository),
        "head": head,
        "parent": parent,
        "changed_paths": changed_paths,
    }


def _invalid_result_contract_source(
    attempt: Path,
    endpoint: Endpoint,
    envelope: Envelope,
    started: Mapping[str, Any],
) -> dict[str, Any] | None:
    failed_path = attempt / "failed.json"
    invalid_path = attempt / "worker-result.invalid.txt"
    task_path = attempt / "transport-task.json"
    if (
        not failed_path.is_file()
        or not invalid_path.is_file()
        or not task_path.is_file()
        or (attempt / "completed.json").exists()
        or (attempt / "worker-result.json").exists()
    ):
        return None
    failed = _read_object(failed_path, "Worker failed result")
    terminal_fields = {
        "schema_version", "message_id", "run_id", "adapter", "status",
        "native_identity", "error_code", "evidence",
    }
    if (
        set(failed) != terminal_fields
        or failed.get("schema_version") != "slk.transport-result/v1"
        or failed.get("message_id") != envelope.message_id
        or failed.get("run_id") != envelope.run_id
        or failed.get("adapter") != "dsh-worker"
        or failed.get("status") != "failed"
        or failed.get("error_code") != "DSH_RESULT_INVALID"
        or not isinstance(failed.get("native_identity"), Mapping)
        or not isinstance(failed.get("evidence"), list)
        or "worker-result.invalid.txt" not in failed["evidence"]
    ):
        return None
    task_digest = started.get("native_request_sha256")
    if not isinstance(task_digest, str):
        return None
    try:
        task = verify_task_file(task_path.resolve(), task_digest)
        task_endpoint = Endpoint.from_dict(task["endpoint"])
        task_envelope = Envelope.from_dict(task["envelope"])
        from .adapters.dsh import DshAdapter

        expected_result_path = (
            Path(str(endpoint.address["cwd"]))
            / ".slk-transport"
            / envelope.message_id
            / "worker-result.json"
        ).resolve()
        task_matches = (
            task_endpoint == endpoint
            and task_envelope == envelope
            and task.get("message_id") == envelope.message_id
            and task.get("run_id") == envelope.run_id
            and task.get("go_id") == envelope.go_id
            and task.get("cell_id") == envelope.cell_id
            and task.get("result_contract") == DshAdapter.legacy_result_contract(endpoint, envelope)
            and task.get("result_path") == str(expected_result_path)
        )
    except (KeyError, TypeError, ValueError, TaskFileError, CompletionError):
        return None
    if not task_matches:
        return None
    invalid = _read_object(invalid_path, "invalid Worker result")
    identity = invalid.get("identity")
    completed = invalid.get("completed")
    if (
        set(invalid) != {"schema_version", "identity", "status", "completed"}
        or invalid.get("schema_version") != "slk.worker-result-contract/v1"
        or invalid.get("status") != "completed"
        or not isinstance(identity, Mapping)
        or set(identity) != {"schema_version", "message_id", "run_id", "role_instance_id"}
        or identity.get("schema_version") != "slk.worker-result/v1"
        or identity.get("message_id") != envelope.message_id
        or identity.get("run_id") != envelope.run_id
        or identity.get("role_instance_id") != endpoint.role_instance_id
        or not isinstance(completed, Mapping)
        or set(completed) != {"candidate", "next_payload", "blocker", "evidence"}
        or completed.get("blocker") is not None
    ):
        return None
    candidate = completed.get("candidate")
    next_payload = completed.get("next_payload")
    evidence = completed.get("evidence")
    if (
        not isinstance(candidate, Mapping)
        or set(candidate) != {"kind", "commit"}
        or candidate.get("kind") != "commit"
        or not isinstance(candidate.get("commit"), str)
        or len(str(candidate["commit"])) != 40
        or any(character not in "0123456789abcdef" for character in str(candidate["commit"]))
        or not isinstance(next_payload, Mapping)
        or set(next_payload) != {"candidate_repository"}
        or not isinstance(next_payload.get("candidate_repository"), str)
        or not isinstance(evidence, Mapping)
    ):
        return None
    repository = Path(str(next_payload["candidate_repository"])).resolve()
    if repository != Path(str(endpoint.address["cwd"])).resolve():
        return None
    snapshot = _candidate_repository_snapshot(repository)
    raw_changed_paths = evidence.get("changed_paths")
    if (
        snapshot["head"] != candidate["commit"]
        or evidence.get("candidate_commit") != candidate["commit"]
        or evidence.get("candidate_parent") != snapshot["parent"]
        or not isinstance(raw_changed_paths, list)
        or sorted(raw_changed_paths) != snapshot["changed_paths"]
    ):
        return None
    return {
        "failed": failed,
        "candidate": dict(candidate),
        **snapshot,
    }


def _continuation_root(request: Mapping[str, Any]) -> Path:
    name = (
        "invalid-result-supplement"
        if request.get("recovery_mode") == "INVALID_RESULT_CONTRACT"
        else "worker-continuation"
    )
    return Path(str(request["source_attempt_root"])) / name


def _native_v2_worker_session(
    started_path: Path,
    endpoint: Endpoint,
    envelope: Envelope,
) -> str | None:
    try:
        started = validate_native_start(
            started_path,
            adapter=endpoint.adapter,
            run_id=envelope.run_id,
            cell_id=envelope.cell_id,
            message_id=envelope.message_id,
            request_sha256=envelope.payload_sha256,
        )
    except NativeActivityError:
        return None
    native_task = started["native_task"]
    if native_task["kind"] != "dsh-session":
        return None
    session_id = native_task["id"]
    return session_id if isinstance(session_id, str) else None


def _legacy_completed_worker_session(
    attempt: Path,
    endpoint: Endpoint,
    envelope: Envelope,
    started: Mapping[str, Any],
    completed: Mapping[str, Any] | None,
    result: Mapping[str, Any] | None,
    runtime_projection: Mapping[str, Any],
    *,
    attempt_number: int,
    candidate_message_id: str,
    checker_token_already_committed: bool,
) -> str | None:
    """Read one closed 4.3.4 start only after its completed candidate already owns Checker TOKEN."""

    if (
        not checker_token_already_committed
        or completed is None
        or result is None
        or set(started) != _LEGACY_WORKER_START_FIELDS
        or started.get("status") != "started"
        or started.get("message_id") != envelope.message_id
        or started.get("run_id") != envelope.run_id
        or started.get("instance_id") != endpoint.address.get("instance_id")
    ):
        return None
    session_id = started.get("session_id")
    native_identity = completed.get("native_identity")
    if (
        not isinstance(session_id, str)
        or not session_id.startswith("session-")
        or set(completed)
        != {
            "schema_version",
            "message_id",
            "run_id",
            "adapter",
            "status",
            "native_identity",
            "error_code",
            "evidence",
        }
        or completed.get("schema_version") != "slk.transport-result/v1"
        or completed.get("message_id") != envelope.message_id
        or completed.get("run_id") != envelope.run_id
        or completed.get("adapter") != "dsh-worker"
        or completed.get("status") != "completed"
        or completed.get("error_code") is not None
        or completed.get("evidence")
        != ["started.json", "worker-result.json", "native.stdout.txt", "native.stderr.txt"]
        or not isinstance(native_identity, Mapping)
        or set(native_identity)
        != {"instance_id", "session_id", "exit_code", "worker_outcome", "blocker_cause"}
        or native_identity.get("instance_id") != endpoint.address.get("instance_id")
        or native_identity.get("session_id") != session_id
        or native_identity.get("exit_code") != 0
        or native_identity.get("worker_outcome") != "completed"
        or native_identity.get("blocker_cause") is not None
    ):
        return None
    task_path = attempt / "transport-task.json"
    try:
        task = verify_task_file(task_path.resolve(), str(started.get("task_sha256")))
        task_endpoint = Endpoint.from_dict(task["endpoint"])
        task_envelope = Envelope.from_dict(task["envelope"])
        from .adapters.dsh import DshAdapter

        expected_result_path = (
            Path(str(endpoint.address["cwd"]))
            / ".slk-transport"
            / envelope.message_id
            / "worker-result.json"
        ).resolve()
        task_matches = (
            task_endpoint == endpoint
            and task_envelope == envelope
            and task.get("message_id") == envelope.message_id
            and task.get("run_id") == envelope.run_id
            and task.get("go_id") == envelope.go_id
            and task.get("cell_id") == envelope.cell_id
            and json.dumps(task.get("result_contract"), sort_keys=True)
            in {
                json.dumps(DshAdapter().result_contract(endpoint, envelope), sort_keys=True),
                json.dumps(DshAdapter().legacy_result_contract(endpoint, envelope), sort_keys=True),
            }
            and task.get("result_path") == str(expected_result_path)
        )
    except (KeyError, TypeError, ValueError, TaskFileError):
        return None
    candidate = result.get("candidate")
    if not task_matches or not isinstance(candidate, Mapping):
        return None
    candidate_submitted, transport_started = _exact_worker_handoff(
        runtime_projection,
        cell_id=envelope.cell_id,
        attempt=attempt_number,
        candidate=candidate,
        source_message_id=envelope.message_id,
        handoff_message_id=candidate_message_id,
    )
    return session_id if candidate_submitted and transport_started else None


def build_continuation_request(
    attempt_root: Path | str,
    checker_endpoint_raw: Mapping[str, Any],
    runtime_projection: Mapping[str, Any],
    *,
    plan_revision: int,
    runtime_revision: int,
    token_sequence: int,
    credential_path: Path | str,
    state_command: list[str],
    transport_command: list[str],
    occurred_at: str,
) -> dict[str, Any]:
    """Build one immutable request for the already-started DSH Worker Session."""

    attempt = Path(attempt_root).resolve()
    endpoint_path = attempt / "endpoint.json"
    envelope_path = attempt / "envelope.json"
    started_path = attempt / "started.json"
    result_path = attempt / "worker-result.json"
    completed_path = attempt / "completed.json"
    endpoint = Endpoint.from_dict(_read_object(endpoint_path, "Worker endpoint"))
    envelope = Envelope.from_dict(_read_object(envelope_path, "Worker envelope"))
    checker = Endpoint.from_dict(checker_endpoint_raw)
    started = _read_object(started_path, "Worker started evidence")
    missing_result_failure = _missing_result_failure(attempt, envelope)
    invalid_result_source = _invalid_result_contract_source(attempt, endpoint, envelope, started)
    source_task_sha256: str | None = None
    source_started_sha256: str | None = None
    source_invalid_result_sha256: str | None = None
    source_candidate: dict[str, Any] | None = None
    source_candidate_parent: str | None = None
    source_repository: str | None = None
    source_changed_paths: list[str] | None = None
    supplement_result_contract: dict[str, Any] | None = None
    if result_path.is_file() and completed_path.is_file():
        recovery_mode = "COMPLETED_RESULT"
        result = _read_object(result_path, "Worker result")
        completed = _read_object(completed_path, "Worker terminal result")
        continuation_result_path = result_path
        worker_result_sha256: str | None = _sha256(result_path)
        source_terminal_path = completed_path
    elif missing_result_failure is not None:
        recovery_mode = "MISSING_RESULT"
        result = None
        completed = None
        continuation_result_path = attempt / "worker-continuation" / "recovered-worker-result.json"
        worker_result_sha256 = None
        source_terminal_path = attempt / "failed.json"
    elif invalid_result_source is not None:
        recovery_mode = "INVALID_RESULT_CONTRACT"
        result = None
        completed = None
        continuation_result_path = (
            attempt / "invalid-result-supplement" / "recovered-worker-result.json"
        )
        worker_result_sha256 = None
        source_terminal_path = attempt / "failed.json"
        source_task_sha256 = _sha256(attempt / "transport-task.json")
        source_started_sha256 = _sha256(started_path)
        source_invalid_result_sha256 = _sha256(attempt / "worker-result.invalid.txt")
        source_candidate = dict(invalid_result_source["candidate"])
        source_candidate_parent = str(invalid_result_source["parent"])
        source_repository = str(invalid_result_source["repository"])
        source_changed_paths = list(invalid_result_source["changed_paths"])
        supplement_result_contract = dict(INVALID_SUPPLEMENT_RESULT_CONTRACT)
    else:
        raise CompletionError(
            "WORKER_CONTINUATION_NOT_READY",
            "Worker attempt has no exact recoverable completed, missing, or invalid-result source",
        )
    attempt_number = _source_attempt(runtime_projection, envelope)
    snapshot = runtime_projection.get("runtime_snapshot")
    candidate_message_id = _stable_id(envelope.message_id, "candidate-ready")
    checker_token_already_committed = (
        isinstance(snapshot, Mapping)
        and snapshot.get("token_holder_role_instance_id") == checker.role_instance_id
        and snapshot.get("latest_message_id") == candidate_message_id
    )
    worker_holds_source_token = (
        isinstance(snapshot, Mapping)
        and snapshot.get("token_holder_role_instance_id") == endpoint.role_instance_id
        and snapshot.get("latest_message_id") == envelope.message_id
    )
    if recovery_mode == "INVALID_RESULT_CONTRACT":
        source_event_types = _event_types(
            runtime_projection,
            cell_id=envelope.cell_id,
            attempt=attempt_number,
        )
        if (
            not worker_holds_source_token
            or checker_token_already_committed
            or source_event_types & {"WORK_STARTED", "D0_COMPLETED", "CANDIDATE_SUBMITTED"}
        ):
            raise CompletionError(
                "WORKER_CONTINUATION_NOT_READY",
                "invalid-result supplement requires the original Worker TOKEN and no Worker engineering facts",
            )
    session_id = (
        _native_v2_worker_session(started_path, endpoint, envelope)
        if started.get("schema_version") == "slk.native-start/v2"
        else _legacy_completed_worker_session(
            attempt,
            endpoint,
            envelope,
            started,
            completed,
            result,
            runtime_projection,
            attempt_number=attempt_number,
            candidate_message_id=candidate_message_id,
            checker_token_already_committed=checker_token_already_committed,
        )
        if recovery_mode == "COMPLETED_RESULT"
        else None
    )
    configured_session_id = endpoint.address.get("session_id")
    if (
        endpoint.role != "worker"
        or envelope.receiver_role != "worker"
        or endpoint.role_instance_id != envelope.receiver_role_instance_id
        or checker.role != "checker"
        or checker.run_id != envelope.run_id
        or not isinstance(session_id, str)
        or not session_id.startswith("session-")
        or (configured_session_id is not None and session_id != configured_session_id)
        or (
            recovery_mode == "COMPLETED_RESULT"
            and (
                completed is None
                or result is None
                or completed.get("status") != "completed"
                or result.get("status") != "completed"
                or result.get("message_id") != envelope.message_id
                or result.get("role_instance_id") != endpoint.role_instance_id
            )
        )
        or not isinstance(snapshot, Mapping)
        or snapshot.get("method_version") != "4.3.6"
        or snapshot.get("plan_revision") != plan_revision
        or snapshot.get("runtime_revision") != runtime_revision
        or snapshot.get("token_sequence") != token_sequence
        or not (worker_holds_source_token or checker_token_already_committed)
    ):
        raise CompletionError(
            "WORKER_CONTINUATION_NOT_READY",
            "terminal Worker evidence, exact Session, Run, or Checker binding does not match",
        )
    if (
        isinstance(plan_revision, bool)
        or plan_revision < 1
        or isinstance(runtime_revision, bool)
        or runtime_revision < 1
        or isinstance(token_sequence, bool)
        or token_sequence < 1
        or not state_command
        or not transport_command
        or not all(isinstance(item, str) and item for item in state_command + transport_command)
    ):
        raise CompletionError("WORKER_CONTINUATION_NOT_READY", "closed commands and positive revisions are required")
    _timestamp(occurred_at)
    credential = Path(credential_path).resolve()
    return {
        "schema_version": CONTINUATION_SCHEMA,
        "method_version": "4.3.6",
        "run_id": envelope.run_id,
        "go_id": envelope.go_id,
        "cell_id": envelope.cell_id,
        "attempt": attempt_number,
        "plan_revision": plan_revision,
        "runtime_revision": runtime_revision,
        "source_message_id": envelope.message_id,
        "source_attempt_root": str(attempt),
        "continuation_result_path": str(
            attempt
            / ("invalid-result-supplement" if recovery_mode == "INVALID_RESULT_CONTRACT" else "worker-continuation")
            / "result.json"
        ),
        "source_endpoint_sha256": _sha256(endpoint_path),
        "source_envelope_sha256": _sha256(envelope_path),
        "source_runtime_projection_sha256": canonical_json_sha256(runtime_projection),
        "source_runtime_snapshot": {
            field: snapshot.get(field)
            for field in (
                "method_version",
                "plan_revision",
                "runtime_revision",
                "token_sequence",
                "token_holder_role_instance_id",
                "latest_message_id",
            )
        },
        "recovery_mode": recovery_mode,
        "worker_result_path": str(continuation_result_path.resolve()),
        "worker_result_sha256": worker_result_sha256,
        "source_terminal_sha256": _sha256(source_terminal_path),
        "source_task_sha256": source_task_sha256,
        "source_started_sha256": source_started_sha256,
        "source_invalid_result_sha256": source_invalid_result_sha256,
        "source_candidate": source_candidate,
        "source_candidate_parent": source_candidate_parent,
        "source_repository": source_repository,
        "source_changed_paths": source_changed_paths,
        "supplement_result_contract": supplement_result_contract,
        "worker_role_instance_id": endpoint.role_instance_id,
        "worker_instance_id": str(endpoint.address["instance_id"]),
        "worker_session_id": session_id,
        "checker_endpoint": dict(checker_endpoint_raw),
        "credential_path": str(credential),
        "state_command": list(state_command),
        "transport_command": list(transport_command),
        "token_sequence": token_sequence,
        "checker_token_already_committed": checker_token_already_committed,
        "occurred_at": occurred_at,
    }


def continuation_request_bytes(request: Mapping[str, Any]) -> bytes:
    return (json.dumps(request, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode(
        "utf-8"
    )


def _validate_continuation_request(request: Mapping[str, Any]) -> None:
    if (
        set(request) != CONTINUATION_FIELDS
        or request.get("schema_version") != CONTINUATION_SCHEMA
        or request.get("method_version") != "4.3.6"
    ):
        raise CompletionError("WORKER_CONTINUATION_INVALID", "continuation request is not closed")
    snapshot = request.get("source_runtime_snapshot")
    snapshot_fields = {
        "method_version",
        "plan_revision",
        "runtime_revision",
        "token_sequence",
        "token_holder_role_instance_id",
        "latest_message_id",
    }
    if (
        not isinstance(snapshot, Mapping)
        or set(snapshot) != snapshot_fields
        or snapshot.get("method_version") != "4.3.6"
        or snapshot.get("plan_revision") != request.get("plan_revision")
        or snapshot.get("runtime_revision") != request.get("runtime_revision")
        or snapshot.get("token_sequence") != request.get("token_sequence")
    ):
        raise CompletionError("WORKER_CONTINUATION_INVALID", "frozen runtime snapshot is inconsistent")
    if request.get("recovery_mode") == "INVALID_RESULT_CONTRACT":
        if (
            snapshot.get("token_holder_role_instance_id") != request.get("worker_role_instance_id")
            or snapshot.get("latest_message_id") != request.get("source_message_id")
            or request.get("checker_token_already_committed") is not False
            or request.get("supplement_result_contract") != INVALID_SUPPLEMENT_RESULT_CONTRACT
            or not all(
                request.get(field) is not None
                for field in (
                    "source_task_sha256",
                    "source_started_sha256",
                    "source_invalid_result_sha256",
                    "source_candidate",
                    "source_candidate_parent",
                    "source_repository",
                    "source_changed_paths",
                )
            )
        ):
            raise CompletionError(
                "WORKER_CONTINUATION_INVALID",
                "invalid-result supplement does not bind the original Worker snapshot",
            )
    elif request.get("recovery_mode") in {"COMPLETED_RESULT", "MISSING_RESULT"}:
        if request.get("supplement_result_contract") is not None:
            raise CompletionError("WORKER_CONTINUATION_INVALID", "ordinary continuation has supplement fields")
    else:
        raise CompletionError("WORKER_CONTINUATION_INVALID", "continuation recovery mode is invalid")


def prepare_invalid_result_recovery_envelope(
    source_attempt_root: Path | str,
    checker_endpoint_raw: Mapping[str, Any],
    runtime_projection_path: Path | str,
    *,
    supervisor_role_instance_id: str,
    plan_revision: int,
    runtime_revision: int,
    token_sequence: int,
    worker_credential_path: Path | str,
    checker_credential_path: Path | str,
    state_command: list[str],
    transport_command: list[str],
    occurred_at: str,
    output_path: Path | str,
) -> dict[str, Any]:
    """Read-only preflight that materializes one authenticated Checker recovery envelope."""

    projection_path = Path(runtime_projection_path).resolve()
    projection = _read_object(projection_path, "runtime projection")
    checker = Endpoint.from_dict(checker_endpoint_raw)
    worker_credential = Path(worker_credential_path).resolve()
    checker_credential = Path(checker_credential_path).resolve()
    if (
        checker.role != "checker"
        or not worker_credential.is_file()
        or not checker_credential.is_file()
        or not projection_path.is_file()
    ):
        raise CompletionError(
            "WORKER_CONTINUATION_NOT_READY",
            "active Checker, runtime projection, and sealed role credentials are required",
        )
    continuation = build_continuation_request(
        source_attempt_root,
        checker_endpoint_raw,
        projection,
        plan_revision=plan_revision,
        runtime_revision=runtime_revision,
        token_sequence=token_sequence,
        credential_path=worker_credential,
        state_command=state_command,
        transport_command=transport_command,
        occurred_at=occurred_at,
    )
    if continuation.get("recovery_mode") != "INVALID_RESULT_CONTRACT":
        raise CompletionError(
            "WORKER_CONTINUATION_NOT_READY",
            "prepare entry accepts only an exact invalid-result contract source",
        )
    source_message_id = str(continuation["source_message_id"])
    payload = {
        "source_attempt_root": str(Path(source_attempt_root).resolve()),
        "runtime_projection_path": str(projection_path),
        "plan_revision": plan_revision,
        "runtime_revision": runtime_revision,
        "token_sequence": token_sequence,
        "worker_credential_path": str(worker_credential),
        "checker_credential_path": str(checker_credential),
        "state_command": list(state_command),
        "transport_command": list(transport_command),
        "occurred_at": occurred_at,
    }
    envelope = {
        "schema_version": ENVELOPE_SCHEMA,
        "message_id": _stable_id(source_message_id, "invalid-result-contract-recovery"),
        "token_sequence": token_sequence,
        "run_id": continuation["run_id"],
        "go_id": continuation["go_id"],
        "cell_id": continuation["cell_id"],
        "sender_role": "supervisor",
        "sender_role_instance_id": supervisor_role_instance_id,
        "receiver_role": "checker",
        "receiver_role_instance_id": checker.role_instance_id,
        "receiver_endpoint_version": checker.endpoint_version,
        "payload_type": "WORKER_COMPLETION_RECOVERY",
        "payload_sha256": canonical_json_sha256(payload),
        "payload": payload,
    }
    Envelope.from_dict(envelope)
    destination = Path(output_path).resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    _write_or_reuse_stable_request(destination, envelope)
    return {
        "schema_version": "slk.invalid-result-recovery-readiness/v1",
        "method_version": "4.3.6",
        "status": "INVALID_RESULT_RECOVERY_READY",
        "run_id": continuation["run_id"],
        "cell_id": continuation["cell_id"],
        "source_message_id": source_message_id,
        "recovery_message_id": envelope["message_id"],
        "recovery_mode": continuation["recovery_mode"],
        "candidate": continuation["source_candidate"],
        "worker_session_id": continuation["worker_session_id"],
        "runtime_revision": runtime_revision,
        "token_sequence": token_sequence,
        "envelope_path": str(destination),
        "envelope_sha256": _sha256(destination),
    }


def resume_worker_continuation(request: Mapping[str, Any]) -> dict[str, Any]:
    """Resume exactly the recorded DSH Session and let it execute one bounded suffix."""

    _validate_continuation_request(request)
    from .adapters.dsh import DshAdapter, _positive_seconds
    from .process import windows_no_window_kwargs
    from .subprocess_watch import finish, spawn

    attempt = Path(str(request["source_attempt_root"]))
    endpoint_path = attempt / "endpoint.json"
    envelope_path = attempt / "envelope.json"
    endpoint = Endpoint.from_dict(_read_object(endpoint_path, "Worker endpoint"))
    if (
        _sha256(endpoint_path) != request.get("source_endpoint_sha256")
        or _sha256(envelope_path) != request.get("source_envelope_sha256")
        or endpoint.role_instance_id != request.get("worker_role_instance_id")
        or endpoint.address.get("instance_id") != request.get("worker_instance_id")
    ):
        raise CompletionError(
            "WORKER_CONTINUATION_SOURCE_CHANGED",
            "immutable Worker endpoint or envelope changed before continuation",
        )
    recovery_mode = request.get("recovery_mode")
    terminal_path = attempt / (
        "failed.json"
        if recovery_mode in {"MISSING_RESULT", "INVALID_RESULT_CONTRACT"}
        else "completed.json"
    )
    if recovery_mode not in {"COMPLETED_RESULT", "MISSING_RESULT", "INVALID_RESULT_CONTRACT"} or (
        _sha256(terminal_path) != request.get("source_terminal_sha256")
    ):
        raise CompletionError(
            "WORKER_CONTINUATION_SOURCE_CHANGED",
            "immutable Worker terminal evidence changed before continuation",
        )
    adapter = DshAdapter()
    adapter.validate_address(endpoint)
    configured_session_id = endpoint.address.get("session_id")
    worker_session_id = request.get("worker_session_id")
    if not isinstance(worker_session_id, str) or (
        configured_session_id is not None and configured_session_id != worker_session_id
    ):
        raise CompletionError("WORKER_CONTINUATION_SESSION_MISMATCH", "Worker endpoint does not name the recorded Session")
    resumed_endpoint = Endpoint(
        **{
            **endpoint.__dict__,
            "address": {**endpoint.address, "session_id": worker_session_id},
        }
    )
    adapter.validate_address(resumed_endpoint)
    continuation_root = _continuation_root(request)
    if recovery_mode == "INVALID_RESULT_CONTRACT":
        if continuation_root.exists():
            raise CompletionError(
                "WORKER_INVALID_RESULT_SUPPLEMENT_ALREADY_ATTEMPTED",
                "the one allowed invalid-result supplement already has evidence",
            )
        if (
            _sha256(attempt / "transport-task.json") != request.get("source_task_sha256")
            or _sha256(attempt / "started.json") != request.get("source_started_sha256")
            or _sha256(attempt / "worker-result.invalid.txt")
            != request.get("source_invalid_result_sha256")
        ):
            raise CompletionError(
                "WORKER_CONTINUATION_SOURCE_CHANGED",
                "invalid-result source evidence changed before supplement",
            )
        snapshot = _candidate_repository_snapshot(Path(str(request["source_repository"])))
        if (
            snapshot["head"] != request.get("source_candidate", {}).get("commit")
            or snapshot["parent"] != request.get("source_candidate_parent")
            or snapshot["changed_paths"] != request.get("source_changed_paths")
        ):
            raise CompletionError(
                "WORKER_CONTINUATION_SOURCE_CHANGED",
                "candidate repository changed before result-only supplement",
            )
    continuation_root.mkdir(parents=True, exist_ok=True)
    request_path = continuation_root / "request.json"
    data = continuation_request_bytes(request)
    if request_path.exists() and request_path.read_bytes() != data:
        raise CompletionError("WORKER_CONTINUATION_CONFLICT", "immutable continuation request conflicts")
    if not request_path.exists():
        temporary = request_path.with_suffix(".json.tmp")
        temporary.write_bytes(data)
        temporary.replace(request_path)
    digest = hashlib.sha256(data).hexdigest()
    if recovery_mode == "MISSING_RESULT":
        instruction = (
            "Resume this exact SLK Worker Session only to recover its missing closed result contract and finish "
            "the existing CELL handoff. Do not redo or expand the implementation. Verify the immutable request "
            "SHA-256, inspect the frozen source envelope and current repository candidate, then write one closed "
            "slk.worker-result/v1 JSON object to the request's worker_result_path. It must contain exactly "
            "schema_version, message_id, run_id, role_instance_id, status, candidate, and next_payload; "
            "status must be completed and the identity must match the source attempt. "
            "After writing it, execute the request's transport_command with "
            f"`continue-worker --request {json.dumps(str(request_path))} --sha256 {digest}`. "
            "Do not read, print, copy, or return credential plaintext. "
            f"<slk-worker-continuation-task path={json.dumps(str(request_path))} sha256={json.dumps(digest)} />"
        )
    elif recovery_mode == "INVALID_RESULT_CONTRACT":
        instruction = (
            "Resume this exact SLK Worker Session for one result-only contract correction. Do not edit product "
            "files, change commits, rerun construction, or create a rework round. Verify the immutable request "
            "SHA-256, inspect the frozen invalid result and unchanged candidate, then author one flat completed "
            "slk.worker-result/v1 object at worker_result_path using exactly the worker_result_fields, "
            "next_payload_fields, and d0_fields frozen in supplement_result_contract. Reuse the Worker's real rich "
            "D0 and evidence; the Tool must not transform the old nested object or invent a new schema. Then execute "
            f"the request's transport_command with `continue-worker --request {json.dumps(str(request_path))} "
            f"--sha256 {digest}`. Do not read, print, copy, or return credential plaintext. "
            f"<slk-worker-continuation-task path={json.dumps(str(request_path))} sha256={json.dumps(digest)} />"
        )
    else:
        instruction = (
            "Resume this exact SLK Worker Session only to finish its already-completed CELL handoff. "
            "Verify the immutable request SHA-256, then execute its transport_command with "
            f"`continue-worker --request {json.dumps(str(request_path))} --sha256 {digest}`. "
            "Do not read, print, copy, or return credential plaintext. "
            f"<slk-worker-continuation-task path={json.dumps(str(request_path))} sha256={json.dumps(digest)} />"
        )
    command = adapter.command(resumed_endpoint, instruction)
    environment = os.environ.copy()
    environment.pop("SLK_ROLE_CREDENTIAL", None)
    environment.pop("SLK_OVERWATCHER_CREDENTIAL", None)
    environment["DSH_RUNTIME_ROOT"] = str(resumed_endpoint.address["runtime_root"])
    environment["SLK_DSH_INSTANCE_ID"] = str(request["worker_instance_id"])
    environment["SLK_DSH_SESSION_ID"] = str(request["worker_session_id"])
    timeout = _positive_seconds(resumed_endpoint.address["timeout_seconds"])
    started_at = time.monotonic()
    process = spawn(
        command,
        cwd=str(resumed_endpoint.address["cwd"]),
        env=environment,
        process_kwargs=windows_no_window_kwargs(),
    )
    session_path = adapter._session_root(resumed_endpoint) / f"{worker_session_id}.json"
    while time.monotonic() - started_at < timeout:
        if session_path.is_file() and process.poll() is None:
            break
        if process.poll() is not None:
            break
        time.sleep(0.01)
    if process.poll() is not None or not session_path.is_file():
        process.kill()
        process.communicate()
        raise CompletionError("WORKER_CONTINUATION_START_UNPROVED", "exact resumed DSH Session did not start")
    started_path = continuation_root / "started.json"
    started = {
        "schema_version": "slk.worker-continuation-start/v1",
        "run_id": request["run_id"],
        "source_message_id": request["source_message_id"],
        "instance_id": request["worker_instance_id"],
        "session_id": request["worker_session_id"],
        "request_sha256": digest,
        "status": "started",
    }
    started_bytes = continuation_request_bytes(started)
    if started_path.exists() and started_path.read_bytes() != started_bytes:
        process.kill()
        process.communicate()
        raise CompletionError("WORKER_CONTINUATION_CONFLICT", "continuation start evidence conflicts")
    if not started_path.exists():
        started_path.write_bytes(started_bytes)
    try:
        remaining = timeout - (time.monotonic() - started_at)
        completed = finish(process, remaining)
    except subprocess.TimeoutExpired as exc:
        raise CompletionError("WORKER_CONTINUATION_TIMEOUT", "resumed Worker did not finish the handoff") from exc
    (continuation_root / "native.stdout.txt").write_text(completed.stdout, encoding="utf-8")
    (continuation_root / "native.stderr.txt").write_text(completed.stderr, encoding="utf-8")
    if completed.returncode != 0:
        raise CompletionError("WORKER_CONTINUATION_FAILED", f"resumed Worker exited with {completed.returncode}")
    if recovery_mode == "INVALID_RESULT_CONTRACT":
        snapshot = _candidate_repository_snapshot(Path(str(request["source_repository"])))
        if (
            snapshot["head"] != request.get("source_candidate", {}).get("commit")
            or snapshot["parent"] != request.get("source_candidate_parent")
            or snapshot["changed_paths"] != request.get("source_changed_paths")
        ):
            raise CompletionError(
                "WORKER_CONTINUATION_SOURCE_CHANGED",
                "candidate repository changed during result-only supplement",
            )
    result = _read_object(Path(str(request["continuation_result_path"])), "continuation result")
    if result.get("status") != "CHECKER_DELIVERY_READY" or result.get("source_message_id") != request.get(
        "source_message_id"
    ):
        raise CompletionError(
            "WORKER_CONTINUATION_RESULT_INVALID",
            "continuation result does not prove one staged Checker delivery",
        )
    return result


def _event_types(projection: Mapping[str, Any], *, cell_id: str, attempt: int) -> set[str]:
    events = projection.get("events")
    if not isinstance(events, list):
        return set()
    return {
        str(item.get("event_type"))
        for item in events
        if isinstance(item, Mapping)
        and isinstance(item.get("event_type"), str)
        and item.get("cell_id") == cell_id
        and item.get("attempt") == attempt
    }


def _event_details(value: Mapping[str, Any]) -> Mapping[str, Any]:
    details = value.get("details")
    if isinstance(details, Mapping):
        return details
    serialized = value.get("details_json")
    if isinstance(serialized, str):
        try:
            decoded = json.loads(serialized)
        except json.JSONDecodeError:
            return {}
        if isinstance(decoded, Mapping):
            return decoded
    return {}


def _exact_worker_handoff(
    projection: Mapping[str, Any],
    *,
    cell_id: str,
    attempt: int,
    candidate: Mapping[str, Any],
    source_message_id: str,
    handoff_message_id: str,
) -> tuple[bool, bool]:
    events = projection.get("events")
    if not isinstance(events, list):
        return False, False
    candidate_submitted = False
    transport_started = False
    for item in events:
        if (
            not isinstance(item, Mapping)
            or item.get("cell_id") != cell_id
            or item.get("attempt") != attempt
        ):
            continue
        details = _event_details(item)
        if item.get("event_type") == "CANDIDATE_SUBMITTED":
            candidate_submitted = candidate_submitted or (
                details.get("candidate") == candidate
                and details.get("source_message_id") == source_message_id
                and details.get("handoff_message_id") == handoff_message_id
            )
        if item.get("event_type") == "TRANSPORT_STARTED":
            transport_started = transport_started or details.get("message_id") == handoff_message_id
    return candidate_submitted, transport_started


def _observation_mentions_message(value: Any, message_id: str) -> bool:
    if not isinstance(value, Mapping):
        return False
    if value.get("message_id") == message_id:
        return True
    details: Any = value.get("details")
    if not isinstance(details, Mapping):
        serialized = value.get("details_json")
        if isinstance(serialized, str):
            try:
                details = json.loads(serialized)
            except json.JSONDecodeError:
                details = None
    return isinstance(details, Mapping) and details.get("message_id") == message_id


def inspect_worker_completion(
    attempt_root: Path | str,
    runtime_projection: Mapping[str, Any],
    *,
    observed_at: str,
    cadence_seconds: int,
    previous_inspection: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Classify one Worker terminal/handoff boundary without changing Run state."""

    if isinstance(cadence_seconds, bool) or cadence_seconds < 1:
        raise CompletionError("WORKER_COMPLETION_CADENCE_INVALID", "cadence_seconds must be positive")
    now = _timestamp(observed_at)
    attempt = Path(attempt_root).resolve()
    envelope = Envelope.from_dict(_read_object(attempt / "envelope.json", "Worker envelope"))
    endpoint = Endpoint.from_dict(_read_object(attempt / "endpoint.json", "Worker endpoint"))
    snapshot = runtime_projection.get("runtime_snapshot")
    if not isinstance(snapshot, Mapping):
        raise CompletionError("WORKER_COMPLETION_PROJECTION_INVALID", "runtime snapshot is required")
    token_owner = snapshot.get("token_holder_role_instance_id")
    attempt_number = _source_attempt(runtime_projection, envelope)
    event_types = _event_types(runtime_projection, cell_id=envelope.cell_id, attempt=attempt_number)
    completed_path = attempt / "completed.json"
    completed = completed_path.is_file()
    failed_path = attempt / "failed.json"
    candidate: Mapping[str, Any] | None = None
    handoff_message_id = _stable_id(envelope.message_id, "candidate-ready")
    exact_candidate = False
    exact_transport = False
    if completed:
        worker_result = _read_object(attempt / "worker-result.json", "Worker result")
        raw_candidate = worker_result.get("candidate")
        if (
            worker_result.get("message_id") != envelope.message_id
            or worker_result.get("run_id") != envelope.run_id
            or worker_result.get("role_instance_id") != endpoint.role_instance_id
            or worker_result.get("status") != "completed"
            or not isinstance(raw_candidate, Mapping)
        ):
            raise CompletionError(
                "WORKER_COMPLETION_EVIDENCE_INVALID",
                "terminal Worker result does not match the exact dispatch identity",
            )
        candidate = raw_candidate
        exact_candidate, exact_transport = _exact_worker_handoff(
            runtime_projection,
            cell_id=envelope.cell_id,
            attempt=attempt_number,
            candidate=candidate,
            source_message_id=envelope.message_id,
            handoff_message_id=handoff_message_id,
        )
    base = {
        "schema_version": INSPECTION_SCHEMA,
        "run_id": envelope.run_id,
        "go_id": envelope.go_id,
        "cell_id": envelope.cell_id,
        "attempt": attempt_number,
        "source_message_id": envelope.message_id,
        "worker_role_instance_id": endpoint.role_instance_id,
        "candidate": candidate,
        "worker_outcome": "completed" if completed else None,
        "blocker": None,
        "handoff_message_id": handoff_message_id,
        "observed_at": observed_at,
        "cadence_seconds": cadence_seconds,
        "anomaly_codes": [],
        "notification_already_sent": False,
        "missing_worker_events": [],
    }
    if not completed:
        result_path = attempt / "worker-result.json"
        if failed_path.is_file() and result_path.is_file():
            failed = _read_object(failed_path, "Worker failed result")
            worker_result = _read_object(result_path, "Worker result")
            outcome = worker_result.get("status")
            status_map = {
                "incomplete": "WORKER_INCOMPLETE",
                "blocked": "WORKER_BLOCKED",
                "execution_failure": "WORKER_EXECUTION_FAILURE",
                "timed_out": "WORKER_TIMED_OUT",
            }
            error_map = {key: f"DSH_WORKER_{value.removeprefix('WORKER_')}" for key, value in status_map.items()}
            blocker = worker_result.get("blocker")
            if (
                outcome not in status_map
                or set(worker_result)
                != {
                    "schema_version",
                    "message_id",
                    "run_id",
                    "role_instance_id",
                    "status",
                    "candidate",
                    "next_payload",
                    "blocker",
                }
                or worker_result.get("schema_version") != "slk.worker-result/v1"
                or worker_result.get("message_id") != envelope.message_id
                or worker_result.get("run_id") != envelope.run_id
                or worker_result.get("role_instance_id") != endpoint.role_instance_id
                or worker_result.get("candidate") is not None
                or worker_result.get("next_payload") is not None
                or not isinstance(blocker, Mapping)
                or set(blocker) != {"phase", "cause", "summary", "evidence"}
                or not all(
                    isinstance(blocker.get(field), str) and str(blocker[field]).strip()
                    for field in ("phase", "cause", "summary")
                )
                or not isinstance(blocker.get("evidence"), list)
                or not all(
                    isinstance(item, str) and item.strip()
                    for item in blocker.get("evidence", [])
                )
                or failed.get("schema_version") != "slk.transport-result/v1"
                or failed.get("message_id") != envelope.message_id
                or failed.get("run_id") != envelope.run_id
                or failed.get("adapter") != "dsh-worker"
                or failed.get("status") != "failed"
                or failed.get("error_code") != error_map[outcome]
            ):
                raise CompletionError(
                    "WORKER_COMPLETION_EVIDENCE_INVALID",
                    "non-completed Worker result does not match the exact failed dispatch",
                )
            return {
                **base,
                "status": status_map[outcome],
                "worker_outcome": outcome,
                "blocker": dict(blocker),
                "grace_started_at": None,
            }
        missing_result_failure = _missing_result_failure(attempt, envelope)
        if missing_result_failure is not None:
            return {
                **base,
                "status": "WORKER_INCOMPLETE",
                "worker_outcome": "incomplete",
                "blocker": {
                    "phase": "result_contract",
                    "cause": "RESULT_CONTRACT_MISSING",
                    "summary": "the exact started DSH Worker terminated without its closed result contract",
                    "evidence": ["failed.json", "native.stdout.txt", "native.stderr.txt"],
                },
                "grace_started_at": None,
            }
        return {**base, "status": "IN_PROGRESS", "grace_started_at": None}
    if token_owner != endpoint.role_instance_id and exact_candidate and exact_transport:
        return {**base, "status": "HANDED_OFF_OR_D1", "grace_started_at": None}
    observations = runtime_projection.get("operational_observations")
    notification_already_sent = isinstance(observations, list) and any(
        _observation_mentions_message(item, envelope.message_id) for item in observations
    )
    terminal_time = _file_timestamp(completed_path)
    grace_started = terminal_time if terminal_time <= now else now
    grace_started_at = grace_started.isoformat().replace("+00:00", "Z")
    if previous_inspection is not None:
        if (
            previous_inspection.get("schema_version") != INSPECTION_SCHEMA
            or previous_inspection.get("run_id") != envelope.run_id
            or previous_inspection.get("source_message_id") != envelope.message_id
            or previous_inspection.get("status")
            not in {"COMPLETION_GRACE", "WORKER_COMPLETION_HANDOFF_MISSING"}
        ):
            raise CompletionError("WORKER_COMPLETION_PREVIOUS_INVALID", "previous inspection identity is not exact")
        grace_started_at = str(previous_inspection.get("grace_started_at"))
    elapsed = (now - _timestamp(grace_started_at)).total_seconds()
    if elapsed < cadence_seconds:
        return {**base, "status": "COMPLETION_GRACE", "grace_started_at": grace_started_at}
    return {
        **base,
        "status": "WORKER_COMPLETION_HANDOFF_MISSING",
        "grace_started_at": grace_started_at,
        "anomaly_codes": [
            "WORKER_COMPLETION_HANDOFF_MISSING",
            "COMMUNICATION_RECOVERY_REQUIRED",
        ],
        "notification_already_sent": notification_already_sent,
        "missing_worker_events": sorted(
            {"WORK_STARTED", "D0_COMPLETED"} - event_types
            | ({"CANDIDATE_SUBMITTED"} if not exact_candidate else set())
            | ({"TRANSPORT_STARTED"} if not exact_transport else set())
        ),
    }


Authenticate = Callable[[str, str], int]
WriteEvent = Callable[[dict[str, Any]], str]
StartChecker = Callable[[dict[str, Any], dict[str, Any]], Mapping[str, Any]]
CommitStart = Callable[[dict[str, Any]], Mapping[str, Any]]


def run_worker_continuation(
    request: Mapping[str, Any],
    *,
    authenticate: Authenticate,
    write_event: WriteEvent,
    start_checker: StartChecker,
    commit_start: CommitStart,
    defer_checker_start: bool = False,
) -> dict[str, Any]:
    """Execute the bounded Worker-owned D0/candidate/checker handoff suffix."""

    _validate_continuation_request(request)
    run_id = str(request["run_id"])
    role_instance_id = str(request["worker_role_instance_id"])
    fresh_runtime_revision = authenticate(run_id, role_instance_id)
    if isinstance(fresh_runtime_revision, bool) or not isinstance(fresh_runtime_revision, int) or fresh_runtime_revision < 1:
        raise CompletionError("WORKER_RUNTIME_REVISION_INVALID", "fresh runtime revision is unavailable")
    attempt = Path(str(request["source_attempt_root"]))
    recovery_mode = request.get("recovery_mode")
    if recovery_mode not in {"COMPLETED_RESULT", "MISSING_RESULT", "INVALID_RESULT_CONTRACT"}:
        raise CompletionError("WORKER_CONTINUATION_INVALID", "continuation recovery mode is invalid")
    if recovery_mode == "INVALID_RESULT_CONTRACT" and fresh_runtime_revision != request.get("runtime_revision"):
        raise CompletionError(
            "WORKER_RUNTIME_REVISION_INVALID",
            "invalid-result supplement requires the frozen Worker runtime revision",
        )
    result_path = Path(str(request.get("worker_result_path", ""))).resolve()
    if recovery_mode == "MISSING_RESULT":
        expected_result_path = attempt / "worker-continuation" / "recovered-worker-result.json"
    elif recovery_mode == "INVALID_RESULT_CONTRACT":
        expected_result_path = attempt / "invalid-result-supplement" / "recovered-worker-result.json"
    else:
        expected_result_path = attempt / "worker-result.json"
    expected_result_path = expected_result_path.resolve()
    if result_path != expected_result_path:
        raise CompletionError("WORKER_COMPLETION_EVIDENCE_INVALID", "Worker result path is not exact")
    if recovery_mode == "COMPLETED_RESULT":
        if (
            request.get("worker_result_sha256") is None
            or _sha256(result_path) != request.get("worker_result_sha256")
            or _sha256(attempt / "completed.json") != request.get("source_terminal_sha256")
        ):
            raise CompletionError("WORKER_COMPLETION_EVIDENCE_INVALID", "Worker result hash changed")
    elif recovery_mode == "MISSING_RESULT":
        if (
            request.get("worker_result_sha256") is not None
            or _missing_result_failure(
                attempt,
                Envelope.from_dict(_read_object(attempt / "envelope.json", "Worker envelope")),
            )
            is None
            or _sha256(attempt / "failed.json") != request.get("source_terminal_sha256")
        ):
            raise CompletionError(
                "WORKER_COMPLETION_EVIDENCE_INVALID",
                "missing-result recovery source is not exact",
            )
    elif (
        request.get("worker_result_sha256") is not None
        or _sha256(attempt / "failed.json") != request.get("source_terminal_sha256")
        or _sha256(attempt / "transport-task.json") != request.get("source_task_sha256")
        or _sha256(attempt / "started.json") != request.get("source_started_sha256")
        or _sha256(attempt / "worker-result.invalid.txt")
        != request.get("source_invalid_result_sha256")
    ):
        raise CompletionError(
            "WORKER_COMPLETION_EVIDENCE_INVALID",
            "invalid-result supplement source is not exact",
        )
    worker_result = _read_object(result_path, "Worker result")
    endpoint_path = attempt / "endpoint.json"
    source_endpoint = Endpoint.from_dict(_read_object(endpoint_path, "Worker endpoint"))
    if (
        _sha256(endpoint_path) != request.get("source_endpoint_sha256")
        or _sha256(attempt / "envelope.json") != request.get("source_envelope_sha256")
        or source_endpoint.role != "worker"
        or source_endpoint.run_id != run_id
        or source_endpoint.role_instance_id != role_instance_id
    ):
        raise CompletionError(
            "WORKER_COMPLETION_EVIDENCE_INVALID",
            "authenticated immutable Worker endpoint does not match the continuation",
        )
    source_envelope = Envelope.from_dict(_read_object(attempt / "envelope.json", "Worker envelope"))
    next_payload = worker_result.get("next_payload")
    completed_result_fields = {
        "schema_version",
        "message_id",
        "run_id",
        "role_instance_id",
        "status",
        "candidate",
        "next_payload",
    }
    if (
        frozenset(worker_result) != frozenset(completed_result_fields)
        or worker_result.get("schema_version") != "slk.worker-result/v1"
        or worker_result.get("message_id") != request.get("source_message_id")
        or worker_result.get("run_id") != run_id
        or worker_result.get("role_instance_id") != role_instance_id
        or worker_result.get("status") != "completed"
        or not isinstance(worker_result.get("candidate"), Mapping)
        or set(worker_result["candidate"]) != {"kind", "commit"}
        or worker_result["candidate"].get("kind") != "commit"
        or not isinstance(worker_result["candidate"].get("commit"), str)
        or len(str(worker_result["candidate"]["commit"])) != 40
        or not isinstance(next_payload, Mapping)
    ):
        raise CompletionError("WORKER_COMPLETION_EVIDENCE_INVALID", "Worker next_payload is invalid")
    d0 = next_payload.get("d0")
    changed_paths = next_payload.get("changed_paths", [])
    unproved = next_payload.get("unproved", [])
    repository_value = next_payload.get("candidate_repository", source_endpoint.address.get("cwd"))
    repository = Path(str(repository_value)).resolve()
    if not repository.is_dir():
        raise CompletionError("WORKER_COMPLETION_EVIDENCE_INVALID", "candidate repository is unavailable")
    if recovery_mode == "INVALID_RESULT_CONTRACT":
        required_payload_fields = set(INVALID_SUPPLEMENT_RESULT_CONTRACT["next_payload_fields"])
        required_d0_fields = set(INVALID_SUPPLEMENT_RESULT_CONTRACT["d0_fields"])
        suffix_blocker = next_payload.get("suffix_blocker")
        if (
            request.get("supplement_result_contract") != INVALID_SUPPLEMENT_RESULT_CONTRACT
            or set(next_payload) != required_payload_fields
            or next_payload.get("attempt") != request.get("attempt")
            or next_payload.get("cell_id") != request.get("cell_id")
            or not isinstance(next_payload.get("candidate_repository"), str)
            or not isinstance(changed_paths, list)
            or not changed_paths
            or not all(isinstance(item, str) and item.strip() for item in changed_paths)
            or not isinstance(unproved, list)
            or not all(isinstance(item, str) and item.strip() for item in unproved)
            or not isinstance(d0, Mapping)
            or set(d0) != required_d0_fields
            or not isinstance(d0.get("baseline_commit"), str)
            or len(str(d0["baseline_commit"])) != 40
            or not isinstance(d0.get("branch"), str)
            or not str(d0["branch"]).strip()
            or d0.get("candidate_commit") != worker_result["candidate"]["commit"]
            or sorted(d0.get("changed_paths", [])) != request.get("source_changed_paths")
            or not isinstance(d0.get("evidence_files"), list)
            or not d0["evidence_files"]
            or not all(isinstance(item, str) and item.strip() for item in d0["evidence_files"])
            or not isinstance(d0.get("focused_command"), str)
            or not str(d0["focused_command"]).strip()
            or not isinstance(d0.get("frozen_command"), str)
            or not str(d0["frozen_command"]).strip()
            or not isinstance(d0.get("frozen_command_result"), Mapping)
            or not isinstance(d0.get("green"), Mapping)
            or not isinstance(d0.get("red"), Mapping)
            or d0.get("unproved") != unproved
            or (
                suffix_blocker is not None
                and (
                    not isinstance(suffix_blocker, Mapping)
                    or set(suffix_blocker) != {"phase", "cause", "summary", "evidence"}
                )
            )
        ):
            raise CompletionError(
                "WORKER_COMPLETION_EVIDENCE_INVALID",
                "invalid-result supplement lacks the closed D0, changed-path, or evidence fields",
            )
        snapshot = _candidate_repository_snapshot(repository)
        if (
            worker_result["candidate"] != request.get("source_candidate")
            or str(repository) != request.get("source_repository")
            or snapshot["head"] != worker_result["candidate"]["commit"]
            or snapshot["parent"] != request.get("source_candidate_parent")
            or snapshot["changed_paths"] != sorted(changed_paths)
            or snapshot["changed_paths"] != request.get("source_changed_paths")
        ):
            raise CompletionError(
                "WORKER_COMPLETION_EVIDENCE_INVALID",
                "corrected Worker result does not bind the frozen candidate",
            )
    source_message_id = str(request["source_message_id"])
    handoff_message_id = _stable_id(source_message_id, "candidate-ready")
    checker_token_already_committed = request.get("checker_token_already_committed") is True
    common = {
        "run_id": run_id,
        "go_id": request["go_id"],
        "cell_id": request["cell_id"],
        "attempt": request["attempt"],
        "plan_revision": request["plan_revision"],
        "role_instance_id": role_instance_id,
        "corrects_event_id": None,
        "occurred_at": request["occurred_at"],
    }
    cell_goal = source_envelope.payload.get("cell_goal", next_payload.get("cell_goal"))
    d1_criteria = source_envelope.payload.get("d1_criteria")
    acceptance_criteria = source_envelope.payload.get("acceptance_criteria")
    if d1_criteria is None:
        d1_criteria = acceptance_criteria
    elif acceptance_criteria is not None and acceptance_criteria != d1_criteria:
        raise CompletionError(
            "WORKER_COMPLETION_EVIDENCE_INVALID",
            "d1_criteria and acceptance_criteria conflict",
        )
    source_terminal_path = attempt / (
        "failed.json"
        if recovery_mode in {"MISSING_RESULT", "INVALID_RESULT_CONTRACT"}
        else "completed.json"
    )
    raw_evidence = [
        path
        for path in (
            result_path,
            source_terminal_path,
            attempt / "native.stdout.txt",
            attempt / "native.stderr.txt",
        )
        if path.is_file()
    ]
    evidence_index_path = _continuation_root(request) / "checker-evidence-index.json"
    evidence_index_path.parent.mkdir(parents=True, exist_ok=True)
    evidence_index = {
        "schema_version": "slk.checker-evidence-index/v1",
        "run_id": run_id,
        "go_id": request["go_id"],
        "cell_id": request["cell_id"],
        "attempt": request["attempt"],
        "candidate_message_id": handoff_message_id,
        "entries": [
            {
                "name": path.name,
                "path": str(path.resolve()),
                "byte_length": path.stat().st_size,
                "sha256": _sha256(path),
            }
            for path in raw_evidence
        ],
    }
    _write_or_reuse_stable_request(evidence_index_path, evidence_index)
    evidence_files = [
        str(path.resolve())
        for path in (result_path, source_terminal_path, evidence_index_path)
        if path.is_file()
    ]
    if (
        not isinstance(cell_goal, str)
        or not cell_goal.strip()
        or not isinstance(d1_criteria, list)
        or not d1_criteria
        or not all(isinstance(item, str) and item.strip() for item in d1_criteria)
        or not evidence_files
    ):
        raise CompletionError(
            "WORKER_COMPLETION_EVIDENCE_INVALID",
            "frozen repository, CELL goal, D1 criteria, and immutable evidence are required",
        )
    candidate_payload = {
        "repository": str(repository),
        "candidate": worker_result["candidate"],
        "cell_goal": cell_goal.strip(),
        "d1_criteria": [item.strip() for item in d1_criteria],
        "evidence_files": evidence_files,
    }
    checker = Endpoint.from_dict(request["checker_endpoint"])
    envelope = {
        "schema_version": ENVELOPE_SCHEMA,
        "message_id": handoff_message_id,
        "token_sequence": int(request["token_sequence"])
        if checker_token_already_committed
        else int(request["token_sequence"]) + 1,
        "run_id": run_id,
        "go_id": request["go_id"],
        "cell_id": request["cell_id"],
        "sender_role": "worker",
        "sender_role_instance_id": role_instance_id,
        "receiver_role": "checker",
        "receiver_role_instance_id": checker.role_instance_id,
        "receiver_endpoint_version": checker.endpoint_version,
        "payload_type": "CANDIDATE_READY",
        "payload_sha256": canonical_json_sha256(candidate_payload),
        "payload": candidate_payload,
    }
    Envelope.from_dict(envelope)
    for suffix, event_type, details in (
        ("work-started", "WORK_STARTED", {"source_message_id": source_message_id, "resumed_session_id": request["worker_session_id"]}),
        (
            "d0-completed",
            "D0_COMPLETED",
            {
                "candidate": worker_result["candidate"],
                "d0": d0,
                "changed_paths": changed_paths,
                "unproved": unproved,
            },
        ),
        (
            "candidate-submitted",
            "CANDIDATE_SUBMITTED",
            {
                "candidate": worker_result["candidate"],
                "checker_endpoint_version": request["checker_endpoint"]["endpoint_version"],
                "source_message_id": source_message_id,
                "handoff_message_id": handoff_message_id,
            },
        ),
    ):
        write_event(
            {
                **common,
                "event_id": _stable_id(source_message_id, suffix),
                "event_type": event_type,
                "details": details,
            }
        )
    handoff_runtime_revision = authenticate(run_id, role_instance_id)
    if (
        isinstance(handoff_runtime_revision, bool)
        or not isinstance(handoff_runtime_revision, int)
        or handoff_runtime_revision < fresh_runtime_revision
    ):
        raise CompletionError(
            "WORKER_RUNTIME_REVISION_INVALID",
            "post-event runtime revision is unavailable or moved backwards",
        )
    start = dict(start_checker(dict(request["checker_endpoint"]), envelope))
    if defer_checker_start:
        if start.get("status") != "delivery_ready":
            raise CompletionError(
                "CHECKER_DELIVERY_STAGE_INVALID",
                "Worker must stage one immutable Checker delivery package",
            )
        try:
            endpoint_path = Path(str(start["endpoint_path"])).resolve()
            envelope_path = Path(str(start["envelope_path"])).resolve()
            checker_attempt_root = Path(str(start["attempt_root"])).resolve()
        except KeyError as exc:
            raise CompletionError(
                "CHECKER_DELIVERY_STAGE_INVALID", "staged Checker paths are incomplete"
            ) from exc
        if (
            _read_object(endpoint_path, "staged Checker endpoint")
            != dict(request["checker_endpoint"])
            or _read_object(envelope_path, "staged Checker envelope") != envelope
            or not checker_attempt_root.is_absolute()
        ):
            raise CompletionError(
                "CHECKER_DELIVERY_STAGE_INVALID",
                "staged Checker delivery does not bind the exact candidate",
            )
        return {
            "status": "CHECKER_DELIVERY_READY",
            "run_id": run_id,
            "source_message_id": source_message_id,
            "candidate_message_id": envelope["message_id"],
            "runtime_revision": handoff_runtime_revision,
            "checker_token_already_committed": checker_token_already_committed,
            "endpoint_path": str(endpoint_path),
            "envelope_path": str(envelope_path),
            "attempt_root": str(checker_attempt_root),
        }
    if start.get("status") not in {"started", "completed", "already_started", "ALREADY_STARTED"}:
        raise CompletionError("CHECKER_START_UNPROVED", "Checker native start is not proven")
    try:
        started_path = Path(str(start["started_path"])).resolve()
        endpoint_path = Path(str(start["endpoint_path"])).resolve()
        envelope_path = Path(str(start["envelope_path"])).resolve()
    except KeyError as exc:
        raise CompletionError("CHECKER_START_UNPROVED", "exact native start evidence paths are missing") from exc
    started = _read_object(started_path, "Checker started evidence")
    persisted_endpoint = _read_object(endpoint_path, "Checker delivery endpoint")
    persisted_envelope = _read_object(envelope_path, "Checker delivery envelope")
    if (
        started.get("status") != "started"
        or started.get("run_id") != run_id
        or started.get("message_id") != envelope["message_id"]
        or persisted_endpoint != dict(request["checker_endpoint"])
        or persisted_envelope != envelope
    ):
        raise CompletionError("CHECKER_START_UNPROVED", "exact native start evidence does not match delivery")
    commit_request = {
        "event_id": _stable_id(source_message_id, "checker-transport-started"),
        "transport_receipt_id": _stable_id(source_message_id, "checker-start-receipt"),
        "run_id": run_id,
        "go_id": request["go_id"],
        "cell_id": request["cell_id"],
        "attempt": request["attempt"],
        "plan_revision": request["plan_revision"],
        "expected_runtime_revision": handoff_runtime_revision,
        "message_id": envelope["message_id"],
        "token_sequence": envelope["token_sequence"],
        "from_role_instance_id": role_instance_id,
        "to_role_instance_id": checker.role_instance_id,
        "endpoint_version": checker.endpoint_version,
        "payload_type": "CANDIDATE_READY",
        "payload_sha256": envelope["payload_sha256"],
        "start_evidence": {
            "evidence_id": _stable_id(source_message_id, "checker-start-evidence"),
            "stored_path": str(started_path),
            "sha256": _sha256(started_path),
            "message_id": envelope["message_id"],
            "endpoint_sha256": _sha256(endpoint_path),
            "envelope_sha256": _sha256(envelope_path),
            "native_status": "STARTED",
        },
        "occurred_at": request["occurred_at"],
    }
    committed = commit_start(commit_request)
    committed_revision = committed.get("runtime_revision")
    if (
        committed.get("status") not in {"committed", "idempotent_replay"}
        or isinstance(committed_revision, bool)
        or not isinstance(committed_revision, int)
        or committed_revision <= handoff_runtime_revision
        or committed.get("token_sequence") != envelope["token_sequence"]
        or committed.get("message_id") != envelope["message_id"]
    ):
        raise CompletionError(
            "WORKER_RUNTIME_REVISION_INVALID",
            "delivery commit did not return the exact resulting runtime revision",
        )
    return {
        "status": "CHECKER_STARTED",
        "run_id": run_id,
        "source_message_id": source_message_id,
        "candidate_message_id": envelope["message_id"],
        "runtime_revision": committed_revision,
    }


def _decode_dpapi_plaintext(plain: bytes) -> str:
    """Decode only the two credential encodings produced by supported SLK provisioners."""

    try:
        if plain.startswith(b"\xff\xfe"):
            encoded = plain[2:]
            if not encoded or len(encoded) % 2:
                raise CompletionError(
                    "WORKER_CREDENTIAL_UNAVAILABLE", "Worker credential UTF-16LE bytes are invalid"
                )
            secret = encoded.decode("utf-16-le")
        elif plain.startswith(b"s\x00l\x00k\x00_\x00"):
            if len(plain) % 2:
                raise CompletionError(
                    "WORKER_CREDENTIAL_UNAVAILABLE", "Worker credential UTF-16LE bytes are invalid"
                )
            secret = plain.decode("utf-16-le")
        elif plain.startswith(b"slk_"):
            secret = plain.decode("utf-8", errors="strict")
        else:
            raise CompletionError(
                "WORKER_CREDENTIAL_UNAVAILABLE", "Worker credential plaintext is invalid"
            )
    except UnicodeDecodeError as exc:
        raise CompletionError("WORKER_CREDENTIAL_UNAVAILABLE", "Worker credential plaintext is invalid") from exc
    if secret.endswith("\0"):
        secret = secret[:-1]
    if "\0" in secret:
        raise CompletionError(
            "WORKER_CREDENTIAL_UNAVAILABLE", "Worker credential contains an embedded NUL"
        )
    suffix = secret[4:]
    if (
        not secret.startswith("slk_")
        or len(suffix) != 64
        or any(character not in "0123456789abcdef" for character in suffix)
    ):
        raise CompletionError("WORKER_CREDENTIAL_UNAVAILABLE", "Worker credential shape is invalid")
    return secret


def unprotect_dpapi_hex(path: Path | str) -> str:
    """Decrypt one CurrentUser DPAPI hex blob without emitting its plaintext."""

    if os.name != "nt":
        raise CompletionError("WORKER_CREDENTIAL_UNAVAILABLE", "DPAPI is available only on Windows")
    try:
        encoded = Path(path).read_text(encoding="ascii").strip()
        protected = bytes.fromhex(encoded)
    except (OSError, UnicodeError, ValueError) as exc:
        raise CompletionError("WORKER_CREDENTIAL_UNAVAILABLE", "Worker credential blob is invalid") from exc
    if not protected:
        raise CompletionError("WORKER_CREDENTIAL_UNAVAILABLE", "Worker credential blob is empty")

    class DataBlob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]

    buffer = ctypes.create_string_buffer(protected)
    incoming = DataBlob(len(protected), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte)))
    outgoing = DataBlob()
    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    if not crypt32.CryptUnprotectData(
        ctypes.byref(incoming), None, None, None, None, 0, ctypes.byref(outgoing)
    ):
        raise CompletionError("WORKER_CREDENTIAL_UNAVAILABLE", "DPAPI rejected the Worker credential")
    try:
        plain = ctypes.string_at(outgoing.pbData, outgoing.cbData)
        secret = _decode_dpapi_plaintext(plain)
    except CompletionError:
        raise
    except ValueError as exc:
        raise CompletionError("WORKER_CREDENTIAL_UNAVAILABLE", "Worker credential plaintext is invalid") from exc
    finally:
        if outgoing.pbData:
            ctypes.memset(outgoing.pbData, 0, outgoing.cbData)
            kernel32.LocalFree(outgoing.pbData)
        ctypes.memset(buffer, 0, len(protected))
    return secret


CheckerAuthenticate = Callable[[str, str, Path, list[str]], Mapping[str, Any]]
ResumeContinuation = Callable[[Mapping[str, Any]], Mapping[str, Any]]
ActivateChecker = Callable[[Mapping[str, Any], Mapping[str, Any]], Mapping[str, Any]]
RecordCheckerD1 = Callable[[Mapping[str, Any], Mapping[str, Any], Path, float], Mapping[str, Any]]
LoadCommittedActivation = Callable[[Mapping[str, Any], int], Mapping[str, Any]]
LoadCurrentProjection = Callable[[str, list[str]], Mapping[str, Any]]


def _default_checker_authenticate(
    run_id: str,
    role_instance_id: str,
    credential_path: Path,
    state_command: list[str],
) -> Mapping[str, Any]:
    credential = unprotect_dpapi_hex(credential_path)
    return _run_json_command(
        state_command,
        ["authenticate-role", "--run-id", run_id, "--role-instance-id", role_instance_id],
        credential=credential,
    )


def _default_load_current_projection(
    run_id: str, state_command: list[str]
) -> Mapping[str, Any]:
    query_path = Path(state_command[0]).resolve().with_name("slk-bi-query.exe")
    if not query_path.is_file():
        raise CompletionError(
            "CHECKER_COMMITTED_TERMINAL_ALREADY_ADVANCED",
            "current Run projection cannot be authenticated",
        )
    try:
        value = _run_json_command(
            [str(query_path)], ["run", "--run-id", run_id], credential=None
        )
    except CompletionError as exc:
        raise CompletionError(
            "CHECKER_COMMITTED_TERMINAL_ALREADY_ADVANCED",
            "current Run projection cannot be authenticated",
        ) from exc
    command = value.pop("_slk_command", None)
    if not isinstance(command, Mapping) or command.get("process_exit") != 0:
        raise CompletionError(
            "CHECKER_COMMITTED_TERMINAL_ALREADY_ADVANCED",
            "current Run projection cannot be authenticated",
        )
    return value


def _activate_staged_checker(
    outcome: Mapping[str, Any],
    continuation: Mapping[str, Any],
    *,
    failed_commit_request_path: Path | None = None,
) -> Mapping[str, Any]:
    """Start OCRV outside DSH, validate native v2 evidence, then commit the handoff."""

    expected_outcome_fields = {
        "status",
        "run_id",
        "source_message_id",
        "candidate_message_id",
        "runtime_revision",
        "endpoint_path",
        "envelope_path",
        "attempt_root",
        "checker_token_already_committed",
    }
    if set(outcome) != expected_outcome_fields or outcome.get("status") != "CHECKER_DELIVERY_READY":
        raise CompletionError("CHECKER_DELIVERY_STAGE_INVALID", "staged Checker delivery result is not closed")
    endpoint_path = Path(str(outcome["endpoint_path"])).resolve()
    envelope_path = Path(str(outcome["envelope_path"])).resolve()
    attempt_root = Path(str(outcome["attempt_root"])).resolve()
    try:
        endpoint = Endpoint.from_dict(_read_object(endpoint_path, "staged Checker endpoint"))
        envelope = Envelope.from_dict(_read_object(envelope_path, "staged Checker envelope"))
    except (TypeError, ValueError) as exc:
        raise CompletionError("CHECKER_DELIVERY_STAGE_INVALID", "staged Checker delivery is invalid") from exc
    if (
        endpoint != Endpoint.from_dict(continuation["checker_endpoint"])
        or endpoint.role != "checker"
        or envelope.run_id != continuation.get("run_id")
        or envelope.cell_id != continuation.get("cell_id")
        or envelope.message_id != outcome.get("candidate_message_id")
        or envelope.message_id != _stable_id(str(continuation["source_message_id"]), "candidate-ready")
        or envelope.sender_role != "worker"
        or envelope.sender_role_instance_id != continuation.get("worker_role_instance_id")
        or envelope.receiver_role_instance_id != endpoint.role_instance_id
        or outcome.get("run_id") != continuation.get("run_id")
        or outcome.get("source_message_id") != continuation.get("source_message_id")
    ):
        raise CompletionError(
            "CHECKER_DELIVERY_STAGE_INVALID", "staged Checker delivery identity does not match the continuation"
        )
    staged_revision = outcome.get("runtime_revision")
    if isinstance(staged_revision, bool) or not isinstance(staged_revision, int) or staged_revision < 1:
        raise CompletionError("WORKER_RUNTIME_REVISION_INVALID", "staged runtime revision is invalid")
    checker_token_already_committed = outcome.get("checker_token_already_committed") is True
    if checker_token_already_committed != (continuation.get("checker_token_already_committed") is True):
        raise CompletionError("CHECKER_DELIVERY_STAGE_INVALID", "Checker TOKEN recovery state changed")
    native_attempt_root = (
        attempt_root / ".native-recovery-v2" / str(continuation["source_message_id"])
        if checker_token_already_committed
        else attempt_root
    )
    attempt = native_attempt_root / envelope.run_id / envelope.message_id
    started_path = attempt / "started.json"
    persisted_endpoint_path = attempt / "endpoint.json"
    persisted_envelope_path = attempt / "envelope.json"
    existing = started_path.exists() or persisted_endpoint_path.exists() or persisted_envelope_path.exists()
    if existing:
        if not all(path.is_file() for path in (started_path, persisted_endpoint_path, persisted_envelope_path)):
            raise CompletionError("CHECKER_START_UNPROVED", "Checker attempt has incomplete immutable evidence")
    else:
        if failed_commit_request_path is not None:
            raise CompletionError(
                "CHECKER_START_UNPROVED",
                "commit-only recovery requires the already proven Checker native start",
            )
        transport_command = continuation.get("transport_command")
        if not isinstance(transport_command, list) or not transport_command:
            raise CompletionError("WORKER_CONTINUATION_INVALID", "transport command is unavailable")
        sent = _run_json_command(
            list(transport_command),
            [
                "send",
                "--endpoint",
                str(endpoint_path),
                "--envelope",
                str(envelope_path),
                "--attempt-root",
                str(native_attempt_root),
            ],
            credential=None,
        )
        command = sent.get("_slk_command")
        if (
            sent.get("status") not in {"started", "completed"}
            or sent.get("run_id") != envelope.run_id
            or sent.get("message_id") != envelope.message_id
            or not isinstance(command, Mapping)
            or command.get("process_exit") != 0
        ):
            raise CompletionError("CHECKER_START_UNPROVED", "OCRV transport did not prove the exact native start")
    if (
        _read_object(persisted_endpoint_path, "Checker delivery endpoint") != _read_object(endpoint_path, "staged Checker endpoint")
        or _read_object(persisted_envelope_path, "Checker delivery envelope") != _read_object(envelope_path, "staged Checker envelope")
    ):
        raise CompletionError("CHECKER_START_UNPROVED", "OCRV immutable delivery evidence conflicts")
    try:
        validate_native_start(
            started_path,
            adapter=endpoint.adapter,
            run_id=envelope.run_id,
            cell_id=envelope.cell_id,
            message_id=envelope.message_id,
            request_sha256=envelope.payload_sha256,
        )
    except NativeActivityError as exc:
        raise CompletionError("CHECKER_START_UNPROVED", "OCRV native-start v2 evidence is invalid") from exc
    if checker_token_already_committed:
        if failed_commit_request_path is not None:
            raise CompletionError(
                "WORKER_COMMIT_RECOVERY_NOT_REQUIRED",
                "Checker TOKEN was already committed before commit-only recovery",
            )
        return {
            "status": "CHECKER_STARTED",
            "runtime_revision": staged_revision,
            "token_sequence": envelope.token_sequence,
            "candidate_message_id": envelope.message_id,
            "checker_token_already_committed": True,
            "native_attempt_path": str(attempt),
        }
    commit_request = {
        "event_id": _stable_id(str(continuation["source_message_id"]), "checker-transport-started"),
        "transport_receipt_id": _stable_id(str(continuation["source_message_id"]), "checker-start-receipt"),
        "run_id": envelope.run_id,
        "go_id": continuation["go_id"],
        "cell_id": envelope.cell_id,
        "attempt": continuation["attempt"],
        "plan_revision": continuation["plan_revision"],
        "expected_runtime_revision": staged_revision,
        "message_id": envelope.message_id,
        "token_sequence": envelope.token_sequence,
        "from_role_instance_id": continuation["worker_role_instance_id"],
        "to_role_instance_id": endpoint.role_instance_id,
        "endpoint_version": endpoint.endpoint_version,
        "payload_type": envelope.payload_type,
        "payload_sha256": envelope.payload_sha256,
        "start_evidence": {
            "evidence_id": _stable_id(str(continuation["source_message_id"]), "checker-start-evidence"),
            "stored_path": str(started_path),
            "sha256": _sha256(started_path),
            "message_id": envelope.message_id,
            "endpoint_sha256": _sha256(persisted_endpoint_path),
            "envelope_sha256": _sha256(persisted_envelope_path),
            "native_status": "STARTED",
        },
        "occurred_at": continuation["occurred_at"],
    }
    worker_credential = unprotect_dpapi_hex(str(continuation["credential_path"]))
    try:
        commit_request_path = (
            _continuation_root(continuation)
            / f"commit-delivery-start-{commit_request['transport_receipt_id']}.json"
        )
        failed_request_sha256: str | None = None
        if failed_commit_request_path is not None:
            failed_path = failed_commit_request_path.resolve()
            if failed_path != commit_request_path.resolve() or not failed_path.is_file():
                raise CompletionError(
                    "WORKER_COMMIT_RECOVERY_EVIDENCE_INVALID",
                    "commit-only recovery requires the exact preserved failed request",
                )
            failed_request = _read_object(failed_path, "failed Checker start commit request")
            if failed_request != commit_request:
                raise CompletionError(
                    "WORKER_COMMIT_RECOVERY_EVIDENCE_INVALID",
                    "failed commit request changed the staged delivery identity",
                )
            authentication = _run_json_command(
                list(continuation["state_command"]),
                [
                    "authenticate-role",
                    "--run-id",
                    str(continuation["run_id"]),
                    "--role-instance-id",
                    str(continuation["worker_role_instance_id"]),
                ],
                credential=worker_credential,
            )
            current_revision = authentication.get("runtime_revision")
            if (
                authentication.get("status") != "authenticated"
                or authentication.get("role") != "worker"
                or authentication.get("role_instance_id")
                != continuation.get("worker_role_instance_id")
                or isinstance(current_revision, bool)
                or not isinstance(current_revision, int)
                or current_revision <= staged_revision
            ):
                raise CompletionError(
                    "WORKER_COMMIT_RECOVERY_AUTHENTICATION_FAILED",
                    "original Worker does not prove a newer current runtime revision",
                )
            failed_request_sha256 = _sha256(failed_path)
            commit_request = {
                **commit_request,
                "expected_runtime_revision": current_revision,
            }
            commit_request_path = (
                _continuation_root(continuation)
                / "commit-only-recovery"
                / f"commit-delivery-start-{commit_request['transport_receipt_id']}.json"
            )
            commit_request_path.parent.mkdir(parents=True, exist_ok=True)
        commit_request_path = _write_or_reuse_stable_request(
            commit_request_path,
            commit_request,
        )
        committed = _run_json_command(
            list(continuation["state_command"]),
            ["commit-delivery-start", "--request", str(commit_request_path)],
            credential=worker_credential,
        )
    finally:
        worker_credential = ""
    committed_revision = committed.get("runtime_revision")
    if (
        committed.get("status") not in {"committed", "idempotent_replay"}
        or isinstance(committed_revision, bool)
        or not isinstance(committed_revision, int)
        or committed_revision <= commit_request["expected_runtime_revision"]
        or committed.get("token_sequence") != envelope.token_sequence
        or committed.get("message_id") != envelope.message_id
    ):
        raise CompletionError("WORKER_RUNTIME_REVISION_INVALID", "Checker start commit is not exact")
    activation = {
        "status": "CHECKER_STARTED",
        "runtime_revision": committed_revision,
        "token_sequence": envelope.token_sequence,
        "candidate_message_id": envelope.message_id,
        "checker_token_already_committed": False,
        "native_attempt_path": str(attempt),
    }
    if failed_commit_request_path is None:
        return activation
    recovery_result_path = _continuation_root(continuation) / "commit-only-recovery" / "result.json"
    recovery_result = {
        "schema_version": "slk.worker-checker-commit-recovery/v1",
        "method_version": "4.3.6",
        **activation,
        "status": "CHECKER_START_COMMITTED",
        "run_id": continuation["run_id"],
        "cell_id": continuation["cell_id"],
        "source_message_id": continuation["source_message_id"],
        "worker_role_instance_id": continuation["worker_role_instance_id"],
        "checker_role_instance_id": endpoint.role_instance_id,
        "transport_receipt_id": commit_request["transport_receipt_id"],
        "failed_request_path": str(failed_commit_request_path.resolve()),
        "failed_request_sha256": failed_request_sha256,
        "recovery_request_path": str(commit_request_path.resolve()),
        "recovery_request_sha256": _sha256(commit_request_path),
    }
    _write_or_reuse_stable_request(recovery_result_path, recovery_result)
    return {**recovery_result, "result_path": str(recovery_result_path.resolve())}


def recover_staged_checker_commit(
    continuation: Mapping[str, Any],
    outcome: Mapping[str, Any],
    *,
    failed_request_path: Path,
) -> Mapping[str, Any]:
    """Commit one already-started Checker delivery after a proven revision-only conflict."""

    return _activate_staged_checker(
        outcome,
        continuation,
        failed_commit_request_path=failed_request_path,
    )


def _load_commit_only_checker_activation(
    continuation: Mapping[str, Any],
    current_runtime_revision: int,
) -> Mapping[str, Any]:
    """Validate a completed commit-only recovery for the original Checker path."""

    root = _continuation_root(continuation)
    result_path = root / "commit-only-recovery" / "result.json"
    result = _read_object(result_path, "commit-only recovery result")
    fields = {
        "schema_version",
        "method_version",
        "status",
        "runtime_revision",
        "token_sequence",
        "candidate_message_id",
        "checker_token_already_committed",
        "native_attempt_path",
        "run_id",
        "cell_id",
        "source_message_id",
        "worker_role_instance_id",
        "checker_role_instance_id",
        "transport_receipt_id",
        "failed_request_path",
        "failed_request_sha256",
        "recovery_request_path",
        "recovery_request_sha256",
    }
    if (
        set(result) != fields
        or result.get("schema_version") != "slk.worker-checker-commit-recovery/v1"
        or result.get("method_version") != "4.3.6"
        or result.get("status") != "CHECKER_START_COMMITTED"
        or result.get("runtime_revision") != current_runtime_revision
        or result.get("run_id") != continuation.get("run_id")
        or result.get("cell_id") != continuation.get("cell_id")
        or result.get("source_message_id") != continuation.get("source_message_id")
        or result.get("worker_role_instance_id") != continuation.get("worker_role_instance_id")
        or result.get("checker_role_instance_id")
        != continuation["checker_endpoint"].get("role_instance_id")
        or result.get("candidate_message_id")
        != _stable_id(str(continuation["source_message_id"]), "candidate-ready")
        or result.get("token_sequence") != int(continuation["token_sequence"]) + 1
        or result.get("checker_token_already_committed") is not False
    ):
        raise CompletionError(
            "WORKER_COMMIT_RECOVERY_EVIDENCE_INVALID",
            "commit-only recovery result does not bind the original Checker delivery",
        )
    failed_path = Path(str(result["failed_request_path"])).resolve()
    recovery_path = Path(str(result["recovery_request_path"])).resolve()
    if (
        failed_path
        != (
            root
            / f"commit-delivery-start-{result['transport_receipt_id']}.json"
        ).resolve()
        or recovery_path
        != (
            root
            / "commit-only-recovery"
            / f"commit-delivery-start-{result['transport_receipt_id']}.json"
        ).resolve()
        or not failed_path.is_file()
        or not recovery_path.is_file()
        or result.get("failed_request_sha256") != _sha256(failed_path)
        or result.get("recovery_request_sha256") != _sha256(recovery_path)
    ):
        raise CompletionError(
            "WORKER_COMMIT_RECOVERY_EVIDENCE_INVALID",
            "commit-only request evidence is missing or changed",
        )
    failed_request = _read_object(failed_path, "failed Checker start commit request")
    recovery_request = _read_object(recovery_path, "recovered Checker start commit request")
    failed_without_revision = dict(failed_request)
    recovery_without_revision = dict(recovery_request)
    failed_revision = failed_without_revision.pop("expected_runtime_revision", None)
    recovery_revision = recovery_without_revision.pop("expected_runtime_revision", None)
    if (
        failed_without_revision != recovery_without_revision
        or failed_request.get("transport_receipt_id") != result.get("transport_receipt_id")
        or isinstance(failed_revision, bool)
        or not isinstance(failed_revision, int)
        or isinstance(recovery_revision, bool)
        or not isinstance(recovery_revision, int)
        or recovery_revision <= failed_revision
        or current_runtime_revision != recovery_revision + 1
    ):
        raise CompletionError(
            "WORKER_COMMIT_RECOVERY_EVIDENCE_INVALID",
            "commit-only recovery changed more than the authenticated runtime revision",
        )
    outcome_path = Path(str(continuation["continuation_result_path"])).resolve()
    outcome = _read_object(outcome_path, "staged Checker delivery result")
    if (
        outcome.get("status") != "CHECKER_DELIVERY_READY"
        or outcome.get("candidate_message_id") != result.get("candidate_message_id")
        or outcome.get("run_id") != continuation.get("run_id")
        or outcome.get("source_message_id") != continuation.get("source_message_id")
    ):
        raise CompletionError(
            "WORKER_COMMIT_RECOVERY_EVIDENCE_INVALID",
            "staged Checker delivery no longer matches the recovered commit",
        )
    endpoint_path = Path(str(outcome["endpoint_path"])).resolve()
    envelope_path = Path(str(outcome["envelope_path"])).resolve()
    endpoint = Endpoint.from_dict(_read_object(endpoint_path, "staged Checker endpoint"))
    envelope = Envelope.from_dict(_read_object(envelope_path, "staged Checker envelope"))
    native_attempt = Path(str(result["native_attempt_path"])).resolve()
    expected_attempt = (
        Path(str(outcome["attempt_root"])).resolve()
        / envelope.run_id
        / envelope.message_id
    )
    if (
        endpoint != Endpoint.from_dict(continuation["checker_endpoint"])
        or envelope.message_id != result.get("candidate_message_id")
        or native_attempt != expected_attempt
        or _read_object(native_attempt / "endpoint.json", "Checker delivery endpoint")
        != _read_object(endpoint_path, "staged Checker endpoint")
        or _read_object(native_attempt / "envelope.json", "Checker delivery envelope")
        != _read_object(envelope_path, "staged Checker envelope")
    ):
        raise CompletionError(
            "WORKER_COMMIT_RECOVERY_EVIDENCE_INVALID",
            "existing Checker native attempt does not match the staged delivery",
        )
    try:
        validate_native_start(
            native_attempt / "started.json",
            adapter=endpoint.adapter,
            run_id=envelope.run_id,
            cell_id=envelope.cell_id,
            message_id=envelope.message_id,
            request_sha256=envelope.payload_sha256,
        )
    except NativeActivityError as exc:
        raise CompletionError(
            "WORKER_COMMIT_RECOVERY_EVIDENCE_INVALID",
            "existing Checker native start is invalid",
        ) from exc
    return {
        "status": "CHECKER_STARTED",
        "runtime_revision": current_runtime_revision,
        "token_sequence": result["token_sequence"],
        "candidate_message_id": result["candidate_message_id"],
        "checker_token_already_committed": False,
        "native_attempt_path": str(native_attempt),
    }


def _run_sealed_checker_terminal(
    request_path: Path,
    request: Mapping[str, Any],
    endpoint: Endpoint,
    *,
    request_sha256: str,
    mode: str,
    result_schema: str,
    error_code: str,
) -> Mapping[str, Any]:
    """Use the one registered headless OCRV host for an existing terminal."""

    command = endpoint.address.get("command")
    runtime_root = Path(str(endpoint.address.get("runtime_root", ""))).resolve()
    if not _nonempty_strings(command) or not runtime_root.is_dir():
        raise CompletionError(error_code, "registered OCRV host command or runtime root is unavailable")
    environment = os.environ.copy()
    for name in (
        "SLK_ROLE_CREDENTIAL",
        "SLK_OVERWATCHER_CREDENTIAL",
        "SLK_NATIVE_START_RECEIPT",
        "SLK_NATIVE_START_CONTEXT",
    ):
        environment.pop(name, None)
    environment.update({
        "SLK_OCRV_RECOVERY_ROLE_INSTANCE_ID": endpoint.role_instance_id,
        "SLK_OCRV_RECOVERY_INVOCATION_ID": str(request["recovery_invocation_id"]),
        "SLK_OCRV_RECOVERY_ENDPOINT_VERSION": str(endpoint.endpoint_version),
    })
    from .process import windows_no_window_kwargs

    completed = subprocess.run(
        [*command, mode, "--request", str(request_path.resolve()), "--output", str(Path(str(request["result_path"])).resolve())],
        cwd=str(runtime_root),
        env=environment,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        **windows_no_window_kwargs(detached=False),
    )
    try:
        stdout = (completed.stdout or b"").decode("utf-8", errors="strict")
        stderr = (completed.stderr or b"").decode("utf-8", errors="strict")
        value = json.loads(stdout)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CompletionError(error_code, "original Checker terminal consumer returned no valid UTF-8 JSON") from exc
    if (
        completed.returncode != 0
        or not _matches(value, {
            "schema_version": result_schema,
            "status": "CHECKER_D1_RECORDED",
            "run_id": request["run_id"],
            "checker_role_instance_id": endpoint.role_instance_id,
            "request_sha256": request_sha256,
        })
    ):
        raise CompletionError(error_code, stderr.strip() or "original Checker terminal consumer failed")
    return value


def consume_staged_checker_terminal(
    request_path: Path,
    *,
    request_sha256: str,
) -> Mapping[str, Any]:
    """Re-enter the original sealed OCRV host only to consume an existing terminal."""

    data = request_path.read_bytes()
    if hashlib.sha256(data).hexdigest() != request_sha256:
        raise CompletionError(
            "CHECKER_RECOVERY_REQUEST_MISMATCH",
            "Checker recovery request hash mismatch",
        )
    request = _read_object(request_path, "Checker recovery request")
    if (
        request.get("schema_version") != CHECKER_RECOVERY_SCHEMA
        or request.get("method_version") != "4.3.6"
    ):
        raise CompletionError(
            "CHECKER_RECOVERY_REQUEST_INVALID",
            "existing-terminal consumption requires the original 4.3.6 Checker request",
        )
    try:
        endpoint = Endpoint.from_dict(request["checker_endpoint"])
    except (KeyError, TypeError, ValueError) as exc:
        raise CompletionError(
            "CHECKER_RECOVERY_REQUEST_INVALID",
            "original Checker endpoint is invalid",
        ) from exc
    if (
        endpoint.role != "checker"
        or endpoint.role_instance_id != request.get("checker_role_instance_id")
        or endpoint.endpoint_version != request.get("checker_endpoint_version")
        or endpoint.run_id != request.get("run_id")
    ):
        raise CompletionError(
            "CHECKER_RECOVERY_IDENTITY_MISMATCH",
            "original Checker endpoint identity is not exact",
        )
    projection = _read_object(Path(str(request["runtime_projection_path"])), "runtime projection")
    continuation = build_continuation_request(
        str(request["source_attempt_root"]),
        request["checker_endpoint"],
        projection,
        plan_revision=int(request["plan_revision"]),
        runtime_revision=int(request["runtime_revision"]),
        token_sequence=int(request["token_sequence"]),
        credential_path=str(request["worker_credential_path"]),
        state_command=list(request["state_command"]),
        transport_command=list(request["transport_command"]),
        occurred_at=str(request["occurred_at"]),
    )
    commit_result = _read_object(
        _continuation_root(continuation) / "commit-only-recovery" / "result.json",
        "commit-only recovery result",
    )
    current_revision = commit_result.get("runtime_revision")
    if isinstance(current_revision, bool) or not isinstance(current_revision, int):
        raise CompletionError(
            "WORKER_COMMIT_RECOVERY_EVIDENCE_INVALID",
            "commit-only recovery runtime revision is invalid",
        )
    _load_commit_only_checker_activation(continuation, current_revision)
    return _run_sealed_checker_terminal(
        request_path,
        request,
        endpoint,
        request_sha256=request_sha256,
        mode="--slk-existing-terminal",
        result_schema=CHECKER_RECOVERY_RESULT_SCHEMA,
        error_code="CHECKER_RECOVERY_COMMAND_FAILED",
    )


def _reuse_committed_checker_delivery(continuation: Mapping[str, Any]) -> Mapping[str, Any]:
    """Locate the immutable candidate package after a legacy false start already moved TOKEN."""

    source_message_id = str(continuation["source_message_id"])
    candidate_message_id = _stable_id(source_message_id, "candidate-ready")
    attempt_root = (
        Path(str(continuation["source_attempt_root"])).resolve()
        / "worker-continuation"
        / "checker-attempts"
    )
    attempt = attempt_root / str(continuation["run_id"]) / candidate_message_id
    endpoint_path = attempt / "endpoint.json"
    envelope_path = attempt / "envelope.json"
    if not endpoint_path.is_file() or not envelope_path.is_file():
        raise CompletionError(
            "CHECKER_COMMITTED_DELIVERY_MISSING",
            "Checker holds TOKEN but the immutable candidate package is unavailable",
        )
    return {
        "status": "CHECKER_DELIVERY_READY",
        "run_id": continuation["run_id"],
        "source_message_id": source_message_id,
        "candidate_message_id": candidate_message_id,
        "runtime_revision": continuation["runtime_revision"],
        "checker_token_already_committed": True,
        "endpoint_path": str(endpoint_path),
        "envelope_path": str(envelope_path),
        "attempt_root": str(attempt_root),
    }


def _record_checker_d1(
    activation: Mapping[str, Any],
    continuation: Mapping[str, Any],
    *,
    checker_credential_path: Path | str,
    timeout_seconds: float,
) -> Mapping[str, Any]:
    """Bind the actual OCRV terminal result to Checker-owned D1 events."""

    native_attempt = Path(str(activation.get("native_attempt_path", ""))).resolve()
    started_path = native_attempt / "started.json"
    checker = Endpoint.from_dict(continuation["checker_endpoint"])
    candidate_message_id = str(activation.get("candidate_message_id", ""))
    try:
        started = validate_native_start(
            started_path,
            adapter=checker.adapter,
            run_id=str(continuation["run_id"]),
            cell_id=str(continuation["cell_id"]),
            message_id=candidate_message_id,
        )
    except NativeActivityError as exc:
        raise CompletionError("CHECKER_D1_EVIDENCE_INVALID", "D1 native start evidence is invalid") from exc
    if started["native_task"]["kind"] != "ocrv-review":
        raise CompletionError(
            "CHECKER_D1_EVIDENCE_INVALID",
            "recovery wrapper start is not actual OCRV D1 evidence",
        )
    if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int, float)) or timeout_seconds <= 0:
        raise CompletionError("CHECKER_D1_EVIDENCE_INVALID", "D1 terminal timeout is invalid")
    credential = unprotect_dpapi_hex(checker_credential_path)
    event_root = native_attempt / "slk-state"
    event_root.mkdir(parents=True, exist_ok=True)

    def write_checker_event(event_type: str, suffix: str, details: Mapping[str, Any], occurred_at: str) -> None:
        request = {
            "event_id": _stable_id(candidate_message_id, suffix),
            "run_id": continuation["run_id"],
            "go_id": continuation["go_id"],
            "cell_id": continuation["cell_id"],
            "attempt": continuation["attempt"],
            "plan_revision": continuation["plan_revision"],
            "role_instance_id": checker.role_instance_id,
            "event_type": event_type,
            "details": dict(details),
            "corrects_event_id": continuation.get('partial_correction_event_id') if event_type != 'D1_STARTED' else None,
            "occurred_at": occurred_at,
        }
        request_path = _write_or_reuse_stable_request(event_root / f"{suffix}.json", request)
        recorded = _run_json_command(
            list(continuation["state_command"]),
            ["write", "--request", str(request_path)],
            credential=credential,
        )
        if recorded.get("status") != "recorded" or recorded.get("run_id") != continuation["run_id"]:
            raise CompletionError("CHECKER_D1_STATE_WRITE_FAILED", f"{event_type} was not recorded")

    try:
        if not continuation.get('partial_correction_event_id'): write_checker_event(
            "D1_STARTED",
            "d1-started-v2",
            {
                "candidate_message_id": candidate_message_id,
                "native_start_path": str(started_path),
                "native_start_sha256": _sha256(started_path),
                "native_task": started["native_task"],
            },
            str(started["observed_at"]),
        )
        deadline = time.monotonic() + float(timeout_seconds)
        completed_path = native_attempt / "completed.json"
        failed_path = native_attempt / "failed.json"
        while time.monotonic() < deadline and not completed_path.is_file() and not failed_path.is_file():
            time.sleep(0.02)
        if completed_path.is_file() == failed_path.is_file():
            raise CompletionError("CHECKER_D1_TERMINAL_UNPROVEN", "OCRV D1 has no unique terminal result")
        terminal_path = completed_path if completed_path.is_file() else failed_path
        terminal = _read_object(terminal_path, "OCRV terminal result")
        terminal_fields = {
            "schema_version",
            "message_id",
            "run_id",
            "adapter",
            "status",
            "native_identity",
            "error_code",
            "evidence",
        }
        expected_terminal_status = "completed" if completed_path.is_file() else "failed"
        if (
            set(terminal) != terminal_fields
            or terminal.get("schema_version") != "slk.transport-result/v1"
            or terminal.get("message_id") != candidate_message_id
            or terminal.get("run_id") != continuation["run_id"]
            or terminal.get("adapter") != checker.adapter
            or terminal.get("status") != expected_terminal_status
            or not isinstance(terminal.get("native_identity"), Mapping)
            or not isinstance(terminal.get("evidence"), list)
        ):
            raise CompletionError(
                "CHECKER_D1_EVIDENCE_INVALID",
                "OCRV D1 terminal does not bind the exact candidate delivery",
            )
        result_path = native_attempt / "ocrv-result.json"
        verdict = "INCOMPLETE"
        result: Mapping[str, Any] | None = None
        aggregate_path: Path | None = None
        if completed_path.is_file():
            result = _read_object(result_path, "OCRV D1 result")
            required_result_fields = {
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
            if (
                set(result) != required_result_fields
                or result.get("schema_version") != "slk.ocrv-d1-result/v1"
                or result.get("run_id") != continuation["run_id"]
                or result.get("cell_id") != continuation["cell_id"]
                or result.get("verdict") not in {"PASS", "FAIL", "INCOMPLETE"}
                or not isinstance(result.get("review"), Mapping)
                or not isinstance(result.get("artifacts"), Mapping)
                or not isinstance(result.get("evidence"), list)
            ):
                raise CompletionError("CHECKER_D1_EVIDENCE_INVALID", "OCRV D1 result is not closed")
            verdict = str(result["verdict"])
            identity = terminal["native_identity"]
            identity_fields = {
                "run_id",
                "cell_id",
                "review_invocation_id",
                "session_id",
                "provider",
                "model",
                "verdict",
                "exit_code",
                "review_segment_count",
            }
            review = result["review"]
            segment_count = identity.get("review_segment_count")
            expected_exit_code = {"PASS": 0, "FAIL": 2, "INCOMPLETE": 3}[verdict]
            if (
                set(identity) != identity_fields
                or identity.get("run_id") != continuation["run_id"]
                or identity.get("cell_id") != continuation["cell_id"]
                or identity.get("review_invocation_id") != result.get("review_invocation_id")
                or identity.get("session_id") != review.get("session_id")
                or identity.get("provider") != review.get("provider")
                or identity.get("model") != review.get("model")
                or identity.get("verdict") != verdict
                or identity.get("exit_code") != expected_exit_code
                or isinstance(review.get("exit_code"), bool)
                or not isinstance(review.get("exit_code"), int)
                or not isinstance(segment_count, int)
                or isinstance(segment_count, bool)
                or segment_count < 0
                or "started.json" not in terminal["evidence"]
                or "ocrv-result.json" not in terminal["evidence"]
            ):
                raise CompletionError(
                    "CHECKER_D1_EVIDENCE_INVALID",
                    "OCRV D1 terminal native identity does not bind the actual result",
                )
            if segment_count == 0:
                if (
                    result.get("review_invocation_id") != started["native_task"]["id"]
                    or result.get("request_sha256") != started["native_request_sha256"]
                ):
                    raise CompletionError(
                        "CHECKER_D1_EVIDENCE_INVALID",
                        "OCRV D1 result does not bind the native request",
                    )
            else:
                aggregate_path = native_attempt / "ocrv-aggregate.json"
                aggregate = _read_object(aggregate_path, "OCRV D1 aggregate")
                aggregate_hash = _sha256(aggregate_path)
                segments = aggregate.get("segments")
                if (
                    result["artifacts"].get("aggregate") != "ocrv-aggregate.json"
                    or result["evidence"] != [aggregate_hash]
                    or "ocrv-aggregate.json" not in terminal["evidence"]
                    or aggregate.get("schema_version") != "slk.ocrv-d1-aggregate/v1"
                    or aggregate.get("run_id") != continuation["run_id"]
                    or aggregate.get("cell_id") != continuation["cell_id"]
                    or aggregate.get("verdict") != verdict
                    or aggregate.get("completed_segment_count") != segment_count
                    or not isinstance(segments, list)
                    or len(segments) != segment_count
                ):
                    raise CompletionError(
                        "CHECKER_D1_EVIDENCE_INVALID",
                        "OCRV D1 aggregate evidence does not bind the terminal result",
                    )
                for ordinal, segment in enumerate(segments, start=1):
                    segment_result_path = (
                        native_attempt
                        / "review-segments"
                        / f"segment-{ordinal:03d}"
                        / "result.json"
                    )
                    if (
                        not isinstance(segment, Mapping)
                        or segment.get("ordinal") != ordinal
                        or not segment_result_path.is_file()
                        or segment.get("result_sha256") != _sha256(segment_result_path)
                    ):
                        raise CompletionError(
                            "CHECKER_D1_EVIDENCE_INVALID",
                            "OCRV D1 aggregate segment evidence is invalid",
                        )
        event_type = {
            "PASS": "D1_PASSED",
            "FAIL": "D1_FAILED",
            "INCOMPLETE": "D1_INCOMPLETE",
        }[verdict]
        details = {
            "candidate_message_id": candidate_message_id,
            "verdict": verdict,
            "native_start_sha256": _sha256(started_path),
            "native_terminal_path": str(terminal_path),
            "native_terminal_sha256": _sha256(terminal_path),
            "native_result_path": str(result_path) if result is not None else None,
            "native_result_sha256": _sha256(result_path) if result is not None else None,
            "native_aggregate_path": str(aggregate_path) if aggregate_path is not None else None,
            "native_aggregate_sha256": _sha256(aggregate_path) if aggregate_path is not None else None,
            "review_invocation_id": result.get("review_invocation_id") if result is not None else None,
            "session_id": result["review"].get("session_id") if result is not None else None,
            "reason_codes": result.get("reason_codes") if result is not None else [terminal.get("error_code")],
        }
        occurred_at = datetime.fromtimestamp(terminal_path.stat().st_mtime, tz=timezone.utc).isoformat().replace(
            "+00:00", "Z"
        )
        suffix = ('d1-partial-' + str(continuation['partial_recovery_invocation_id'])
                  if continuation.get('partial_correction_event_id') else 'd1-result-v2')
        write_checker_event(event_type, suffix, details, occurred_at)
    finally:
        credential = ""
    return {
        "status": "CHECKER_D1_RECORDED",
        "d1_verdict": verdict,
        "d1_event_type": event_type,
        "native_attempt_path": str(native_attempt),
        "native_result_path": str(result_path) if result is not None else None,
    }


def _default_record_checker_d1(
    activation: Mapping[str, Any],
    continuation: Mapping[str, Any],
    credential_path: Path,
    timeout_seconds: float,
) -> Mapping[str, Any]:
    return _record_checker_d1(
        activation,
        continuation,
        checker_credential_path=credential_path,
        timeout_seconds=timeout_seconds,
    )


def execute_checker_recovery(
    request: Mapping[str, Any],
    *,
    request_sha256: str,
    authenticate_checker: CheckerAuthenticate = _default_checker_authenticate,
    resume_continuation: ResumeContinuation = resume_worker_continuation,
    activate_checker: ActivateChecker = _activate_staged_checker,
    record_checker_d1: RecordCheckerD1 = _default_record_checker_d1,
    load_committed_activation: LoadCommittedActivation = _load_commit_only_checker_activation,
) -> dict[str, Any]:
    """Authenticate the exact OCRV Checker before resuming one Worker completion suffix."""

    fields = {
        "schema_version",
        "method_version",
        "recovery_invocation_id",
        "recovery_envelope_message_id",
        "run_id",
        "go_id",
        "cell_id",
        "checker_role_instance_id",
        "checker_endpoint_version",
        "checker_endpoint",
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
        "result_path",
    }
    if set(request) != fields or request.get("schema_version") != CHECKER_RECOVERY_SCHEMA:
        raise CompletionError("CHECKER_RECOVERY_REQUEST_INVALID", "Checker recovery request is not closed")
    if request.get("method_version") != "4.3.6":
        raise CompletionError("CHECKER_RECOVERY_REQUEST_INVALID", "Checker recovery requires SLK 4.3.6")
    role_instance_id = request.get("checker_role_instance_id")
    invocation_id = request.get("recovery_invocation_id")
    endpoint_version = request.get("checker_endpoint_version")
    if (
        os.environ.get("SLK_OCRV_RECOVERY_ROLE_INSTANCE_ID") != role_instance_id
        or os.environ.get("SLK_OCRV_RECOVERY_INVOCATION_ID") != invocation_id
        or os.environ.get("SLK_OCRV_RECOVERY_ENDPOINT_VERSION") != str(endpoint_version)
    ):
        raise CompletionError(
            "CHECKER_RECOVERY_NATIVE_IDENTITY_UNPROVEN",
            "recovery is not running inside the exact OCRV Checker invocation",
        )
    try:
        checker = Endpoint.from_dict(request["checker_endpoint"])
    except (TypeError, ValueError) as exc:
        raise CompletionError("CHECKER_RECOVERY_REQUEST_INVALID", "Checker endpoint is invalid") from exc
    if (
        checker.role != "checker"
        or checker.role_instance_id != role_instance_id
        or checker.endpoint_version != endpoint_version
        or checker.run_id != request.get("run_id")
    ):
        raise CompletionError("CHECKER_RECOVERY_IDENTITY_MISMATCH", "Checker endpoint identity is not exact")
    state_command = request.get("state_command")
    transport_command = request.get("transport_command")
    if (
        not isinstance(state_command, list)
        or not state_command
        or not all(isinstance(item, str) and item for item in state_command)
        or not isinstance(transport_command, list)
        or not transport_command
        or not all(isinstance(item, str) and item for item in transport_command)
    ):
        raise CompletionError("CHECKER_RECOVERY_REQUEST_INVALID", "closed commands are required")
    authentication = authenticate_checker(
        str(request["run_id"]),
        str(role_instance_id),
        Path(str(request["checker_credential_path"])),
        list(state_command),
    )
    authenticated_revision = authentication.get("runtime_revision")
    if (
        authentication.get("status") != "authenticated"
        or authentication.get("role") != "checker"
        or authentication.get("role_instance_id") != role_instance_id
        or isinstance(authenticated_revision, bool)
        or not isinstance(authenticated_revision, int)
    ):
        raise CompletionError(
            "CHECKER_RECOVERY_AUTHENTICATION_FAILED",
            "credential does not prove the current Checker",
        )
    projection = _read_object(Path(str(request["runtime_projection_path"])), "runtime projection")
    continuation = build_continuation_request(
        str(request["source_attempt_root"]),
        request["checker_endpoint"],
        projection,
        plan_revision=int(request["plan_revision"]),
        runtime_revision=int(request["runtime_revision"]),
        token_sequence=int(request["token_sequence"]),
        credential_path=str(request["worker_credential_path"]),
        state_command=list(state_command),
        transport_command=list(transport_command),
        occurred_at=str(request["occurred_at"]),
    )
    if authenticated_revision == request.get("runtime_revision"):
        outcome = (
            _reuse_committed_checker_delivery(continuation)
            if continuation.get("checker_token_already_committed") is True
            else resume_continuation(continuation)
        )
        if outcome.get("status") != "CHECKER_DELIVERY_READY":
            raise CompletionError("CHECKER_RECOVERY_FAILED", "Worker continuation did not stage Checker D1")
        activated = activate_checker(outcome, continuation)
        if (
            activated.get("status") != "CHECKER_STARTED"
            or activated.get("candidate_message_id") != outcome.get("candidate_message_id")
        ):
            raise CompletionError("CHECKER_RECOVERY_FAILED", "external OCRV host did not start Checker D1")
    else:
        activated = load_committed_activation(continuation, authenticated_revision)
        if activated.get("status") != "CHECKER_STARTED":
            raise CompletionError(
                "CHECKER_RECOVERY_AUTHENTICATION_FAILED",
                "newer Checker revision lacks an exact commit-only recovery",
            )
    timeout_seconds = checker.address.get("timeout_seconds")
    if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int, float)) or timeout_seconds <= 0:
        raise CompletionError("CHECKER_RECOVERY_REQUEST_INVALID", "Checker timeout is invalid")
    d1 = record_checker_d1(
        activated,
        continuation,
        Path(str(request["checker_credential_path"])),
        float(timeout_seconds),
    )
    if d1.get("status") != "CHECKER_D1_RECORDED" or d1.get("d1_verdict") not in {
        "PASS",
        "FAIL",
        "INCOMPLETE",
    }:
        raise CompletionError("CHECKER_RECOVERY_FAILED", "actual OCRV D1 result was not recorded")
    return {
        "schema_version": CHECKER_RECOVERY_RESULT_SCHEMA,
        "method_version": "4.3.6",
        "status": "CHECKER_D1_RECORDED",
        "run_id": request["run_id"],
        "cell_id": request["cell_id"],
        "source_message_id": continuation["source_message_id"],
        "worker_session_id": continuation["worker_session_id"],
        "checker_role_instance_id": role_instance_id,
        "checker_endpoint_version": endpoint_version,
        "checker_authenticated": True,
        "authorized_recovery": True,
        "recovery_invocation_id": invocation_id,
        "request_sha256": request_sha256,
        "runtime_revision": activated["runtime_revision"],
        "token_sequence": activated["token_sequence"],
        "checker_token_already_committed": activated["checker_token_already_committed"],
        "native_attempt_path": activated["native_attempt_path"],
        "d1_verdict": d1["d1_verdict"],
        "d1_event_type": d1["d1_event_type"],
        "native_result_path": d1["native_result_path"],
    }


def _exact_digest(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _positive_integer(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 1


def _exact_commit(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 40 and all(
        character in "0123456789abcdef" for character in value
    )


def _nonempty_strings(value: Any) -> bool:
    return isinstance(value, list) and bool(value) and all(
        isinstance(item, str) and bool(item) for item in value
    )


def _matches(value: Any, expected: Mapping[str, Any]) -> bool:
    return isinstance(value, Mapping) and all(value.get(name) == item for name, item in expected.items())


def _committed_event_details(event: Mapping[str, Any]) -> Mapping[str, Any]:
    try:
        value = json.loads(str(event.get("details_json", "")))
    except json.JSONDecodeError as exc:
        raise CompletionError(
            "CHECKER_COMMITTED_TERMINAL_EVIDENCE_INVALID",
            "central event details are invalid",
        ) from exc
    if not isinstance(value, Mapping):
        raise CompletionError(
            "CHECKER_COMMITTED_TERMINAL_EVIDENCE_INVALID",
            "central event details are not an object",
        )
    return value


def _validate_committed_terminal_request(request: Mapping[str, Any], *, source_only: bool = False,
                                         partial_review: Mapping[str, Any] | None = None) -> dict[str, Any]:
    if 'partial_terminal' in request and not source_only:
        from .partial_review import validate_partial_terminal
        try:
            return validate_partial_terminal(request)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise CompletionError('CHECKER_INCOMPLETE_RESUME_EVIDENCE_INVALID', str(exc)) from exc
    fields = {
        "schema_version",
        "method_version",
        "recovery_invocation_id",
        "run_id",
        "go_id",
        "cell_id",
        "attempt",
        "plan_revision",
        "runtime_revision",
        "token_sequence",
        "worker_role_instance_id",
        "checker_role_instance_id",
        "checker_endpoint_version",
        "checker_endpoint",
        "runtime_projection_path",
        "runtime_projection_sha256",
        "candidate_repository",
        "candidate_commit",
        "candidate_parent",
        "candidate_message_id",
        "payload_sha256",
        "candidate_submitted_event_id",
        "transport_started_event_id",
        "commit_request_path",
        "commit_request_sha256",
        "native_attempt_path",
        "raw_review_path",
        "immutable_sha256",
        "checker_credential_path",
        "state_command",
        "transport_command",
        "result_path",
    }
    recovery_terminal = request.get("recovery_terminal")
    if recovery_terminal is not None:
        fields.add("recovery_terminal")
    if (
        set(request) != fields
        or request.get("schema_version") != COMMITTED_TERMINAL_SCHEMA
        or request.get("method_version") != "4.3.6"
        or not all(
            _positive_integer(request.get(name))
            for name in (
                "attempt", "plan_revision", "runtime_revision", "token_sequence",
                "checker_endpoint_version",
            )
        )
        or not all(
            isinstance(request.get(name), str) and bool(request.get(name))
            for name in (
                "recovery_invocation_id",
                "run_id",
                "go_id",
                "cell_id",
                "worker_role_instance_id",
                "checker_role_instance_id",
                "candidate_repository",
                "candidate_message_id",
                "candidate_submitted_event_id",
                "transport_started_event_id",
                "checker_credential_path",
                "result_path",
            )
        )
        or not all(_nonempty_strings(request.get(name)) for name in ("state_command", "transport_command"))
        or not all(_exact_commit(request.get(name)) for name in ("candidate_commit", "candidate_parent"))
        or not all(
            _exact_digest(request.get(name))
            for name in (
                "runtime_projection_sha256",
                "payload_sha256",
                "commit_request_sha256",
            )
        )
    ):
        raise CompletionError(
            "CHECKER_COMMITTED_TERMINAL_REQUEST_INVALID",
            "committed-terminal request is not closed",
        )
    try:
        checker = Endpoint.from_dict(request["checker_endpoint"])
    except (TypeError, ValueError) as exc:
        raise CompletionError(
            "CHECKER_COMMITTED_TERMINAL_REQUEST_INVALID",
            "Checker endpoint is invalid",
        ) from exc
    if (
        checker.role != "checker"
        or checker.agent_runtime != "ocrv"
        or checker.adapter != "ocrv-checker"
        or checker.state != "active"
        or checker.run_id != request["run_id"]
        or checker.role_instance_id != request["checker_role_instance_id"]
        or checker.endpoint_version != request["checker_endpoint_version"]
    ):
        raise CompletionError(
            "CHECKER_COMMITTED_TERMINAL_IDENTITY_MISMATCH",
            "registered Checker identity is not exact",
        )
    if not Path(str(request["checker_credential_path"])).resolve().is_file():
        raise CompletionError(
            "CHECKER_COMMITTED_TERMINAL_REQUEST_INVALID",
            "sealed Checker credential is unavailable",
        )
    state_command = request["state_command"]
    transport_command = request["transport_command"]
    state_path = Path(state_command[0]).resolve()
    python_path = Path(transport_command[0]).resolve()
    transport_path = Path(transport_command[-1]).resolve()
    if (
        len(state_command) != 1
        or state_path.name.lower() != "slk-state.exe"
        or not state_path.is_file()
        or len(transport_command) != 2
        or python_path != Path(sys.executable).resolve()
        or transport_path.name.lower() != "slk-transport.pyz"
        or not transport_path.is_file()
        or state_path.parent != transport_path.parent
    ):
        raise CompletionError(
            "CHECKER_COMMITTED_TERMINAL_REQUEST_INVALID",
            "state or transport command is not the installed closed runtime",
        )

    projection_path = Path(str(request["runtime_projection_path"])).resolve()
    if not projection_path.is_file() or _sha256(projection_path) != request["runtime_projection_sha256"]:
        raise CompletionError(
            "CHECKER_COMMITTED_TERMINAL_EVIDENCE_INVALID",
            "runtime projection is missing or changed",
        )
    projection = _read_object(projection_path, "committed-terminal runtime projection")
    summary = projection.get("summary")
    administrative = projection.get("administrative_snapshot")
    runtime = projection.get("runtime_snapshot")
    events = projection.get("events")
    roles = projection.get("roles")
    token_history = projection.get("token_history")
    shared_state = {"run_id": request["run_id"], "state": "active", "closure_state": "open"}
    if (
        not _matches(projection, {"schema_version": "slk.bi.run/v1", "run_id": request["run_id"]})
        or not _matches(summary, {
            **shared_state, "slk_version": "4.3.6",
            "current_plan_revision": request["plan_revision"],
        })
        or not _matches(administrative, {
            **shared_state, "latest_event_id": (partial_review['d1_incomplete_event_id']
                if partial_review is not None else request["transport_started_event_id"]),
        })
        or not _matches(runtime, {
            "run_id": request["run_id"], "method_version": "4.3.6",
            "plan_revision": request["plan_revision"],
            "runtime_revision": request["runtime_revision"],
            "token_sequence": request["token_sequence"],
            "token_holder_role_instance_id": request["checker_role_instance_id"],
            "latest_message_id": request["candidate_message_id"],
        })
        or not all(isinstance(value, list) for value in (events, roles, token_history))
        or not token_history
    ):
        raise CompletionError(
            "CHECKER_COMMITTED_TERMINAL_ALREADY_ADVANCED",
            "current Run no longer exposes the exact committed Checker boundary",
        )
    checker_roles = [
        role
        for role in roles
        if isinstance(role, Mapping)
        and role.get("role") == "checker"
        and role.get("role_instance_id") == request["checker_role_instance_id"]
    ]
    worker_roles = [
        role
        for role in roles
        if isinstance(role, Mapping)
        and role.get("role") == "worker"
        and role.get("role_instance_id") == request["worker_role_instance_id"]
    ]
    if len(checker_roles) != 1 or len(worker_roles) != 1:
        raise CompletionError(
            "CHECKER_COMMITTED_TERMINAL_IDENTITY_MISMATCH",
            "current Worker or Checker role identity is missing or duplicated",
        )
    checker_role = checker_roles[0]
    worker_role = worker_roles[0]
    endpoint_rows = checker_role.get("endpoints")
    matching_endpoint = [
        row
        for row in endpoint_rows
        if isinstance(row, Mapping)
        and row.get("endpoint_version") == checker.endpoint_version
        and row.get("transport_adapter") == checker.adapter
        and row.get("state") == "active"
        and row.get("retired_at") is None
    ] if isinstance(endpoint_rows, list) else []
    if (
        checker_role.get("agent_runtime") != "ocrv"
        or checker_role.get("lifecycle") != "active"
        or len(matching_endpoint) != 1
        or worker_role.get("agent_runtime") != "dsh"
        or worker_role.get("lifecycle") != "active"
    ):
        raise CompletionError(
            "CHECKER_COMMITTED_TERMINAL_IDENTITY_MISMATCH",
            "current Worker or Checker role is not active and exact",
        )

    candidate_matches = []
    transport_matches = []
    for event in events:
        if not isinstance(event, Mapping):
            continue
        if (
            event.get("cell_id") == request["cell_id"]
            and event.get("attempt") == request["attempt"]
            and event.get("event_type") in {"D1_STARTED", "D1_PASSED", "D1_FAILED", "D1_INCOMPLETE"}
        ):
            if partial_review is not None and event.get('event_id') == partial_review.get(
                {'D1_STARTED': 'd1_started_event_id', 'D1_INCOMPLETE': 'd1_incomplete_event_id'}.get(event.get('event_type'), '')
            ) and event.get('author_role_instance_id') == request['checker_role_instance_id'] and (
                _committed_event_details(event).get('candidate_message_id') == request['candidate_message_id']
            ):
                continue
            raise CompletionError(
                "CHECKER_COMMITTED_TERMINAL_ALREADY_ADVANCED",
                "the target attempt already has a D1 event",
            )
        event_type = event.get("event_type")
        if event_type not in {"CANDIDATE_SUBMITTED", "TRANSPORT_STARTED"}:
            continue
        details = _committed_event_details(event)
        if (
            event_type == "CANDIDATE_SUBMITTED"
            and details.get("handoff_message_id") == request["candidate_message_id"]
        ):
            candidate_matches.append((event, details))
        if (
            event_type == "TRANSPORT_STARTED"
            and details.get("message_id") == request["candidate_message_id"]
        ):
            transport_matches.append((event, details))
    if len(candidate_matches) != 1 or len(transport_matches) != 1:
        raise CompletionError(
            "CHECKER_COMMITTED_TERMINAL_EVIDENCE_INVALID",
            "candidate submission or committed transport event is missing or duplicated",
        )
    candidate_event, candidate_details = candidate_matches[0]
    transport_event, transport_details = transport_matches[0]
    expected_scope = (
        request["go_id"],
        request["cell_id"],
        request["attempt"],
        request["worker_role_instance_id"],
    )
    if (
        candidate_event.get("event_id") != request["candidate_submitted_event_id"]
        or transport_event.get("event_id") != request["transport_started_event_id"]
        or tuple(candidate_event.get(name) for name in ("go_id", "cell_id", "attempt", "author_role_instance_id"))
        != expected_scope
        or tuple(transport_event.get(name) for name in ("go_id", "cell_id", "attempt", "author_role_instance_id"))
        != expected_scope
        or candidate_details.get("candidate")
        != {"kind": "commit", "commit": request["candidate_commit"]}
        or candidate_details.get("checker_endpoint_version") != checker.endpoint_version
    ):
        raise CompletionError(
            "CHECKER_COMMITTED_TERMINAL_EVIDENCE_INVALID",
            "central candidate or handoff identity does not match the request",
        )
    last_token = token_history[-1]
    if (
        not isinstance(last_token, Mapping)
        or last_token.get("event_type") != "TOKEN_HANDED_OFF"
        or last_token.get("from_role_instance_id") != request["worker_role_instance_id"]
        or last_token.get("to_role_instance_id") != request["checker_role_instance_id"]
        or last_token.get("go_id") != request["go_id"]
        or last_token.get("cell_id") != request["cell_id"]
        or last_token.get("message_id") != request["candidate_message_id"]
        or last_token.get("token_sequence") != request["token_sequence"]
    ):
        raise CompletionError(
            "CHECKER_COMMITTED_TERMINAL_ALREADY_ADVANCED",
            "TOKEN history no longer ends at the exact Checker handoff",
        )

    commit_path = Path(str(request["commit_request_path"])).resolve()
    if not commit_path.is_file() or _sha256(commit_path) != request["commit_request_sha256"]:
        raise CompletionError(
            "CHECKER_COMMITTED_TERMINAL_EVIDENCE_INVALID",
            "commit-delivery-start request is missing or changed",
        )
    commit = _read_object(commit_path, "commit-delivery-start request")
    commit_fields = {
        "event_id",
        "transport_receipt_id",
        "run_id",
        "go_id",
        "cell_id",
        "attempt",
        "plan_revision",
        "expected_runtime_revision",
        "message_id",
        "token_sequence",
        "from_role_instance_id",
        "to_role_instance_id",
        "endpoint_version",
        "payload_type",
        "payload_sha256",
        "start_evidence",
        "occurred_at",
    }
    start_evidence = commit.get("start_evidence")
    native_attempt = Path(str(request["native_attempt_path"])).resolve()
    started_path = native_attempt / "started.json"
    if (
        set(commit) != commit_fields
        or commit.get("event_id") != request["transport_started_event_id"]
        or commit.get("run_id") != request["run_id"]
        or commit.get("go_id") != request["go_id"]
        or commit.get("cell_id") != request["cell_id"]
        or commit.get("attempt") != request["attempt"]
        or commit.get("plan_revision") != request["plan_revision"]
        or isinstance(commit.get("expected_runtime_revision"), bool)
        or not isinstance(commit.get("expected_runtime_revision"), int)
        or commit.get("expected_runtime_revision") >= request["runtime_revision"]
        or commit.get("message_id") != request["candidate_message_id"]
        or commit.get("token_sequence") != request["token_sequence"]
        or commit.get("from_role_instance_id") != request["worker_role_instance_id"]
        or commit.get("to_role_instance_id") != request["checker_role_instance_id"]
        or commit.get("endpoint_version") != checker.endpoint_version
        or commit.get("payload_type") != "CANDIDATE_READY"
        or commit.get("payload_sha256") != request["payload_sha256"]
        or not isinstance(start_evidence, Mapping)
        or Path(str(start_evidence.get("stored_path", ""))).resolve() != started_path
        or start_evidence.get("message_id") != request["candidate_message_id"]
        or start_evidence.get("native_status") != "STARTED"
        or transport_details.get("transport_receipt_id") != commit.get("transport_receipt_id")
        or transport_details.get("start_evidence_id") != start_evidence.get("evidence_id")
    ):
        raise CompletionError(
            "CHECKER_COMMITTED_TERMINAL_EVIDENCE_INVALID",
            "commit-delivery-start does not bind the current candidate handoff",
        )

    immutable = request.get("immutable_sha256")
    expected_names = (
        {"endpoint.json", "envelope.json", "started.json", "ocrv-request.json"}
        if recovery_terminal is not None or source_only
        else {
            "endpoint.json", "envelope.json", "started.json", "ocrv-request.json",
            "completed.json", "ocrv-result.json", "raw_review",
        }
    )
    if (
        not isinstance(immutable, Mapping)
        or set(immutable) != expected_names
        or not all(_exact_digest(value) for value in immutable.values())
        or native_attempt.name != request["candidate_message_id"]
        or native_attempt.parent.name != request["run_id"]
        or (partial_review is None and (native_attempt / "failed.json").exists())
    ):
        raise CompletionError(
            "CHECKER_COMMITTED_TERMINAL_EVIDENCE_INVALID",
            "immutable OCRV evidence index is invalid",
        )
    evidence_paths = {
        name: native_attempt / name
        for name in expected_names
        if name != "raw_review"
    }
    if partial_review is not None:
        evidence_paths['ocrv-request.json'] = native_attempt / 'review-segments/segment-001/request.json'
    raw_review_path = Path(str(request["raw_review_path"])).resolve()
    if recovery_terminal is None and not source_only:
        evidence_paths["raw_review"] = raw_review_path
    if any(
        not path.is_file() or _sha256(path) != immutable[name]
        for name, path in evidence_paths.items()
    ):
        raise CompletionError(
            "CHECKER_COMMITTED_TERMINAL_EVIDENCE_INVALID",
            "immutable OCRV evidence is missing or changed",
        )
    if (
        start_evidence.get("sha256") != immutable["started.json"]
        or start_evidence.get("endpoint_sha256") != immutable["endpoint.json"]
        or start_evidence.get("envelope_sha256") != immutable["envelope.json"]
        or transport_details.get("start_evidence_sha256") != immutable["started.json"]
        or transport_details.get("endpoint_sha256") != immutable["endpoint.json"]
        or transport_details.get("envelope_sha256") != immutable["envelope.json"]
    ):
        raise CompletionError(
            "CHECKER_COMMITTED_TERMINAL_EVIDENCE_INVALID",
            "central commit hashes do not match immutable OCRV evidence",
        )
    adapter = OcrvAdapter()
    try:
        delivery = parse_delivery(
            _read_object(evidence_paths["endpoint.json"], "OCRV endpoint"),
            _read_object(evidence_paths["envelope.json"], "OCRV envelope"),
        )
        adapter.validate_address(delivery.endpoint)
        started = validate_native_start(
            evidence_paths["started.json"],
            adapter=checker.adapter,
            run_id=str(request["run_id"]),
            cell_id=str(request["cell_id"]),
            message_id=str(request["candidate_message_id"]),
            request_sha256=str(request["payload_sha256"]),
        )
    except (AdapterError, ContractError, NativeActivityError, TypeError, ValueError) as exc:
        raise CompletionError(
            "CHECKER_COMMITTED_TERMINAL_EVIDENCE_INVALID",
            "OCRV endpoint, envelope or native start is invalid",
        ) from exc
    persisted_endpoint = delivery.endpoint
    envelope = delivery.envelope
    payload = envelope.payload
    if (
        persisted_endpoint != checker
        or envelope.run_id != request["run_id"]
        or envelope.go_id != request["go_id"]
        or envelope.cell_id != request["cell_id"]
        or envelope.message_id != request["candidate_message_id"]
        or envelope.sender_role != "worker"
        or envelope.sender_role_instance_id != request["worker_role_instance_id"]
        or envelope.receiver_role != "checker"
        or envelope.receiver_role_instance_id != request["checker_role_instance_id"]
        or envelope.receiver_endpoint_version != checker.endpoint_version
        or envelope.token_sequence != request["token_sequence"]
        or envelope.payload_type != "CANDIDATE_READY"
        or envelope.payload_sha256 != request["payload_sha256"]
        or not isinstance(payload, Mapping)
        or payload.get("candidate") != {"kind": "commit", "commit": request["candidate_commit"]}
        or Path(str(payload.get("repository", ""))).resolve()
        != Path(str(request["candidate_repository"])).resolve()
    ):
        raise CompletionError(
            "CHECKER_COMMITTED_TERMINAL_EVIDENCE_INVALID",
            "OCRV delivery identity does not match the committed candidate",
        )
    ocrv_request = _read_object(evidence_paths["ocrv-request.json"], "OCRV request")
    if (
        ocrv_request.get("schema_version") != "slk.ocrv-d1-request/v2"
        or ocrv_request.get("run_id") != request["run_id"]
        or ocrv_request.get("cell_id") != request["cell_id"]
        or ocrv_request.get("candidate")
        != {"kind": "commit", "commit": request["candidate_commit"]}
        or Path(str(ocrv_request.get("repository", ""))).resolve()
        != Path(str(request["candidate_repository"])).resolve()
        or started.get("native_task", {}).get("kind") != "ocrv-review"
        or started.get("native_request_sha256") != immutable["ocrv-request.json"]
    ):
        raise CompletionError(
            "CHECKER_COMMITTED_TERMINAL_EVIDENCE_INVALID",
            "OCRV native request does not bind the committed candidate",
        )
    if source_only: return {"checker": checker, 'frozen_projection': projection}
    terminal_attempt = native_attempt
    result_request_path = evidence_paths["ocrv-request.json"]
    terminal_request_name = "ocrv-request.json"
    if recovery_terminal is not None:
        if not isinstance(recovery_terminal, Mapping):
            raise CompletionError(
                "CHECKER_COMMITTED_TERMINAL_EVIDENCE_INVALID", "recovery terminal is not an object"
            )
        recovery_fields = {
            "native_attempt_path", "started_sha256", "completed_sha256",
            "ocrv_result_sha256", "resume_request_sha256", "raw_review_sha256",
        }
        terminal_attempt = Path(str(recovery_terminal.get("native_attempt_path", ""))).resolve()
        recovered = {
            "started.json": recovery_terminal.get("started_sha256"),
            "completed.json": recovery_terminal.get("completed_sha256"),
            "ocrv-result.json": recovery_terminal.get("ocrv_result_sha256"),
            "ocrv-resume-request.json": recovery_terminal.get("resume_request_sha256"),
            "raw_review": recovery_terminal.get("raw_review_sha256"),
        }
        recovered_paths = {
            "started.json": terminal_attempt / "started.json",
            "completed.json": terminal_attempt / "completed.json",
            "ocrv-result.json": terminal_attempt / "ocrv-result.json",
            "ocrv-resume-request.json": terminal_attempt / "ocrv-resume-request.json",
            "raw_review": raw_review_path,
        }
        if (
            set(recovery_terminal) != recovery_fields
            or terminal_attempt.parent.parent != native_attempt / "resume-incomplete-checker"
            or any(not _exact_digest(value) for value in recovered.values())
            or any(not path.is_file() or _sha256(path) != recovered[name]
                   for name, path in recovered_paths.items())
        ):
            raise CompletionError(
                "CHECKER_COMMITTED_TERMINAL_EVIDENCE_INVALID", "recovery terminal evidence is invalid"
            )
        try:
            started = validate_native_start(
                recovered_paths["started.json"], adapter=checker.adapter,
                run_id=str(request["run_id"]), cell_id=str(request["cell_id"]),
                message_id=str(request["candidate_message_id"]),
                request_sha256=str(request["payload_sha256"]),
                native_request_sha256=str(recovered["ocrv-resume-request.json"]),
            )
        except NativeActivityError as exc:
            raise CompletionError(
                "CHECKER_COMMITTED_TERMINAL_EVIDENCE_INVALID", "recovery OCRV start is invalid"
            ) from exc
        evidence_paths.update(recovered_paths)
        result_request_path = recovered_paths["ocrv-resume-request.json"]
        terminal_request_name = "ocrv-resume-request.json"
    try:
        terminal = DeliveryResult.from_dict(
            _read_object(evidence_paths["completed.json"], "OCRV terminal")
        )
        raw_result = _read_object(evidence_paths["ocrv-result.json"], "OCRV result")
        verdict = raw_result.get("verdict")
        if verdict not in VERDICT_EXIT_CODES:
            raise AdapterError("OCRV_RESULT_INVALID", "OCRV verdict is invalid")
        result = adapter.validate_existing_result(
            evidence_paths["ocrv-result.json"],
            result_request_path,
            envelope,
            VERDICT_EXIT_CODES[str(verdict)],
        )
    except (AdapterError, ContractError) as exc:
        raise CompletionError(
            "CHECKER_COMMITTED_TERMINAL_EVIDENCE_INVALID",
            "OCRV terminal or result is invalid",
        ) from exc
    identity = terminal.native_identity
    review = result["review"]
    identity_fields = {
        "run_id", "cell_id", "review_invocation_id", "session_id", "provider",
        "model", "verdict", "exit_code", "review_segment_count",
    }
    if (
        terminal.status != "completed"
        or terminal.adapter != checker.adapter
        or terminal.run_id != request["run_id"]
        or terminal.message_id != request["candidate_message_id"]
        or terminal.error_code is not None
        or not {"started.json", terminal_request_name, "ocrv-result.json"}.issubset(terminal.evidence)
        or set(identity) != identity_fields
        or identity.get("review_segment_count") != 0
        or review.get("status") != "complete"
        or identity.get("run_id") != request["run_id"]
        or identity.get("cell_id") != request["cell_id"]
        or identity.get("review_invocation_id") != started["native_task"]["id"]
        or identity.get("review_invocation_id") != result["review_invocation_id"]
        or identity.get("session_id") != review["session_id"]
        or identity.get("provider") != review["provider"]
        or identity.get("model") != review["model"]
        or identity.get("verdict") != result["verdict"]
        or identity.get("exit_code") != VERDICT_EXIT_CODES[str(result["verdict"])]
        or Path(str(result["artifacts"].get("raw_review", ""))).resolve() != raw_review_path
    ):
        raise CompletionError(
            "CHECKER_COMMITTED_TERMINAL_EVIDENCE_INVALID",
            "OCRV terminal and result do not form one completed review",
        )
    raw_review = _read_object(raw_review_path, "OCRV raw review")
    manifest = raw_review.get("manifest")
    coverage = manifest.get("coverage") if isinstance(manifest, Mapping) else None
    manifest_input = manifest.get("input") if isinstance(manifest, Mapping) else None
    execution = manifest.get("execution") if isinstance(manifest, Mapping) else None
    selected = coverage.get("selected") if isinstance(coverage, Mapping) else None
    completed = coverage.get("completed") if isinstance(coverage, Mapping) else None
    reused = coverage.get("reused") if isinstance(coverage, Mapping) else None
    failed = coverage.get("failed") if isinstance(coverage, Mapping) else None
    waived = coverage.get("waived") if isinstance(coverage, Mapping) else None
    if (
        raw_review.get("status") != "complete"
        or raw_review.get("session_id") != review.get("session_id")
        or not isinstance(manifest, Mapping)
        or manifest.get("schema_version") != "ocr.run-manifest/v1"
        or manifest.get("run_id") != review.get("session_id")
        or manifest.get("operation") != "review"
        or manifest.get("terminal_state") != "complete"
        or not isinstance(manifest_input, Mapping)
        or manifest_input.get("requested_head") != request["candidate_commit"]
        or manifest_input.get("resolved_head") != request["candidate_commit"]
        or manifest_input.get("resolved_base") != request["candidate_parent"]
        or manifest_input.get("exact_range")
        != f"{request['candidate_parent']}..{request['candidate_commit']}"
        or not isinstance(execution, Mapping)
        or execution.get("provider") != review.get("provider")
        or execution.get("model") != review.get("model")
        or not isinstance(selected, list)
        or not selected
        or not isinstance(completed, list)
        or not isinstance(reused, list)
        or failed != []
        or waived != []
        or {json.dumps(item, sort_keys=True) for item in selected}
        != {json.dumps(item, sort_keys=True) for item in [*completed, *reused]}
    ):
        raise CompletionError(
            "CHECKER_COMMITTED_TERMINAL_EVIDENCE_INVALID",
            "OCRV raw review manifest does not prove complete candidate coverage",
        )
    continuation = {
        "run_id": request["run_id"],
        "go_id": request["go_id"],
        "cell_id": request["cell_id"],
        "attempt": request["attempt"],
        "plan_revision": request["plan_revision"],
        "source_message_id": request["candidate_message_id"],
        "checker_endpoint": request["checker_endpoint"],
        "state_command": request["state_command"],
        "occurred_at": str(started["observed_at"]),
    }
    activation = {
        "status": "CHECKER_STARTED",
        "runtime_revision": request["runtime_revision"],
        "token_sequence": request["token_sequence"],
        "candidate_message_id": request["candidate_message_id"],
        "checker_token_already_committed": True,
        "native_attempt_path": str(terminal_attempt),
    }
    return {
        "checker": checker,
        "continuation": continuation,
        "activation": activation,
        "frozen_projection": projection,
    }


def _committed_terminal_drift_invalid() -> None:
    raise CompletionError(
        "CHECKER_COMMITTED_TERMINAL_ALREADY_ADVANCED",
        "current runtime drift is not one authenticated Overwatcher-only update",
    )


def _projection_additions(
    frozen: Mapping[str, Any], current: Mapping[str, Any], name: str, identity: str
) -> list[Mapping[str, Any]]:
    before, after = frozen.get(name), current.get(name)
    if not isinstance(before, list) or not isinstance(after, list):
        _committed_terminal_drift_invalid()
    before_by_id = {row.get(identity): row for row in before if isinstance(row, Mapping)}
    after_by_id = {row.get(identity): row for row in after if isinstance(row, Mapping)}
    if (
        len(before_by_id) != len(before)
        or len(after_by_id) != len(after)
        or any(not isinstance(item, str) or not item for item in after_by_id)
        or any(after_by_id.get(item) != row for item, row in before_by_id.items())
    ):
        _committed_terminal_drift_invalid()
    return [row for item, row in after_by_id.items() if item not in before_by_id]


def _rebind_overwatcher_only_committed_boundary(
    request: Mapping[str, Any], frozen: Mapping[str, Any], current: Mapping[str, Any],
    authenticated_revision: int,
) -> int:
    """Accept one revision only when it is a closed Overwatcher status update."""

    old_runtime, now_runtime = frozen.get("runtime_snapshot"), current.get("runtime_snapshot")
    if not isinstance(old_runtime, Mapping) or not isinstance(now_runtime, Mapping):
        _committed_terminal_drift_invalid()
    revision = old_runtime.get("runtime_revision")
    exact_fields = (
        "summary", "administrative_snapshot", "boundaries_json", "go_nodes", "roles",
        "plan_revisions", "events", "token_history", "evidence",
        "reconciliation_receipts", "method_adoption_receipts",
    )
    runtime_ow_fields = {"runtime_revision", "latest_event_id", "overwatcher_status", "committed_at"}
    old_stable = {key: value for key, value in old_runtime.items() if key not in runtime_ow_fields}
    now_stable = {key: value for key, value in now_runtime.items() if key not in runtime_ow_fields}
    if (
        isinstance(revision, bool) or not isinstance(revision, int)
        or authenticated_revision != revision + 1
        or now_runtime.get("runtime_revision") != authenticated_revision
        or current.get("schema_version") != "slk.bi.run/v1"
        or current.get("run_id") != request["run_id"]
        or old_stable != now_stable
        or any(current.get(name) != frozen.get(name) for name in exact_fields)
    ):
        _committed_terminal_drift_invalid()

    roles = current.get("roles")
    watchers = [row for row in roles if isinstance(row, Mapping) and row.get("role") == "overwatcher"
                and row.get("lifecycle") == "active"] if isinstance(roles, list) else []
    additions = {
        "status": _projection_additions(
            frozen, current, "overwatcher_native_status_receipts", "status_id"
        ),
        "incident": _projection_additions(
            frozen, current, "overwatcher_incident_transitions", "transition_id"
        ),
        "observation": _projection_additions(
            frozen, current, "operational_observations", "observation_id"
        ),
        "cycle": _projection_additions(frozen, current, "overwatch_cycles", "cycle_id"),
        "binding": _projection_additions(
            frozen, current, "overwatcher_binding_transitions", "transition_id"
        ),
    }
    if (
        len(watchers) != 1 or len(additions["status"]) != 1
        or additions["cycle"] or additions["binding"]
    ):
        _committed_terminal_drift_invalid()
    watcher, status = watchers[0], additions["status"][0]
    status_id, liveness = status.get("status_id"), status.get("native_liveness")
    if (
        now_runtime.get("latest_event_id") != status_id
        or status.get("role_instance_id") != watcher.get("role_instance_id")
        or status.get("session_id") != watcher.get("session_id")
        or status.get("binding_revision") != now_runtime.get("overwatcher_binding_revision")
        or liveness not in {"IN_PROGRESS", "COMPLETED", "MISSING", "MISMATCHED"}
        or not _exact_digest(status.get("evidence_sha256"))
        or status.get("observed_at") != now_runtime.get("committed_at")
    ):
        _committed_terminal_drift_invalid()

    expected_incidents = 0 if liveness == "IN_PROGRESS" else 1
    if len(additions["incident"]) != expected_incidents:
        _committed_terminal_drift_invalid()
    if expected_incidents:
        incident = additions["incident"][0]
        if not _matches(incident, {
            "transition_id": f"incident-open-{status_id}",
            "binding_revision": status.get("binding_revision"),
            "incident_code": "OVERWATCHER_CONTINUITY_VIOLATION", "state": "OPEN",
            "evidence_path": status.get("evidence_path"),
            "evidence_sha256": status.get("evidence_sha256"),
            "occurred_at": status.get("observed_at"),
        }) or now_runtime.get("overwatcher_status") != "VIOLATION":
            _committed_terminal_drift_invalid()
    elif now_runtime.get("overwatcher_status") != old_runtime.get("overwatcher_status"):
        _committed_terminal_drift_invalid()

    allowed_kinds = {
        "DELIVERY_UNCONFIRMED", "DELIVERY_RETRYING", "ACTIVITY_UNPROVEN", "RECORD_CONFLICT",
        "RECOVERY_ESCALATED", "PROJECTION_REFRESH_REQUESTED", "WORKER_COMPLETION_HANDOFF_MISSING",
    }
    if any(
        row.get("overwatcher_role_instance_id") != watcher.get("role_instance_id")
        or row.get("kind") not in allowed_kinds
        for row in additions["observation"]
    ):
        _committed_terminal_drift_invalid()
    return authenticated_revision


def execute_committed_checker_terminal(
    request: Mapping[str, Any],
    *,
    request_sha256: str,
    authenticate_checker: CheckerAuthenticate = _default_checker_authenticate,
    record_checker_d1: RecordCheckerD1 = _default_record_checker_d1,
    load_current_projection: LoadCurrentProjection = _default_load_current_projection,
) -> dict[str, Any]:
    """Authenticate the original Checker and record one already-complete native D1."""

    if not _exact_digest(request_sha256):
        raise CompletionError(
            "CHECKER_COMMITTED_TERMINAL_REQUEST_INVALID", "request SHA-256 is invalid"
        )
    validated = _validate_committed_terminal_request(request)
    checker: Endpoint = validated["checker"]
    if (
        os.environ.get("SLK_OCRV_RECOVERY_ROLE_INSTANCE_ID") != checker.role_instance_id
        or os.environ.get("SLK_OCRV_RECOVERY_INVOCATION_ID")
        != request["recovery_invocation_id"]
        or os.environ.get("SLK_OCRV_RECOVERY_ENDPOINT_VERSION")
        != str(checker.endpoint_version)
    ):
        raise CompletionError(
            "CHECKER_COMMITTED_TERMINAL_NATIVE_IDENTITY_UNPROVEN",
            "terminal consumption is not running inside the exact OCRV Checker host",
        )
    authentication = authenticate_checker(
        str(request["run_id"]),
        checker.role_instance_id,
        Path(str(request["checker_credential_path"])),
        list(request["state_command"]),
    )
    authenticated_revision = authentication.get("runtime_revision")
    if (
        authentication.get("status") != "authenticated"
        or authentication.get("role") != "checker"
        or authentication.get("role_instance_id") != checker.role_instance_id
        or isinstance(authenticated_revision, bool)
        or not isinstance(authenticated_revision, int)
    ):
        raise CompletionError(
            "CHECKER_COMMITTED_TERMINAL_AUTHENTICATION_FAILED",
            "sealed credential does not prove the current Checker",
        )
    activation = dict(validated["activation"])
    if authenticated_revision != request["runtime_revision"]:
        current_projection = load_current_projection(
            str(request["run_id"]), list(request["state_command"])
        )
        activation["runtime_revision"] = _rebind_overwatcher_only_committed_boundary(
            request,
            validated["frozen_projection"],
            current_projection,
            authenticated_revision,
        )
    timeout_seconds = checker.address.get("timeout_seconds")
    if (
        isinstance(timeout_seconds, bool)
        or not isinstance(timeout_seconds, (int, float))
        or timeout_seconds <= 0
    ):
        raise CompletionError(
            "CHECKER_COMMITTED_TERMINAL_REQUEST_INVALID", "Checker timeout is invalid"
        )
    d1 = record_checker_d1(
        activation,
        validated["continuation"],
        Path(str(request["checker_credential_path"])),
        float(timeout_seconds),
    )
    verdict = d1.get("d1_verdict")
    if (
        d1.get("status") != "CHECKER_D1_RECORDED"
        or verdict not in {"PASS", "FAIL", "INCOMPLETE"}
        or d1.get("d1_event_type") != {
            "PASS": "D1_PASSED", "FAIL": "D1_FAILED", "INCOMPLETE": "D1_INCOMPLETE",
        }[str(verdict)]
    ):
        raise CompletionError(
            "CHECKER_COMMITTED_TERMINAL_RECORD_FAILED", "existing OCRV D1 was not recorded"
        )
    return {
        "schema_version": COMMITTED_TERMINAL_RESULT_SCHEMA,
        "method_version": "4.3.6",
        "status": "CHECKER_D1_RECORDED",
        "run_id": request["run_id"],
        "cell_id": request["cell_id"],
        "attempt": request["attempt"],
        "candidate_message_id": request["candidate_message_id"],
        "checker_role_instance_id": checker.role_instance_id,
        "checker_endpoint_version": checker.endpoint_version,
        "checker_authenticated": True,
        "authorized_existing_terminal": True,
        "recovery_invocation_id": request["recovery_invocation_id"],
        "request_sha256": request_sha256,
        "runtime_revision": authenticated_revision,
        "token_sequence": request["token_sequence"],
        "native_attempt_path": validated["activation"]["native_attempt_path"],
        "d1_verdict": d1["d1_verdict"],
        "d1_event_type": d1["d1_event_type"],
        "native_result_path": d1["native_result_path"],
    }


def consume_committed_checker_terminal(
    request_path: Path,
    *,
    request_sha256: str,
) -> Mapping[str, Any]:
    """Launch the sealed Checker host only after the committed terminal chain is complete."""

    data = request_path.read_bytes()
    if hashlib.sha256(data).hexdigest() != request_sha256:
        raise CompletionError(
            "CHECKER_COMMITTED_TERMINAL_REQUEST_MISMATCH",
            "committed-terminal request hash mismatch",
        )
    request = _read_object(request_path, "committed-terminal request")
    validated = _validate_committed_terminal_request(request)
    checker: Endpoint = validated["checker"]
    value = _run_sealed_checker_terminal(
        request_path,
        request,
        checker,
        request_sha256=request_sha256,
        mode="--slk-committed-terminal",
        result_schema=COMMITTED_TERMINAL_RESULT_SCHEMA,
        error_code="CHECKER_COMMITTED_TERMINAL_COMMAND_FAILED",
    )
    if (
        set(value) != COMMITTED_TERMINAL_RESULT_FIELDS
        or value.get("method_version") != "4.3.6"
        or value.get("d1_verdict") not in {"PASS", "FAIL", "INCOMPLETE"}
    ):
        raise CompletionError(
            "CHECKER_COMMITTED_TERMINAL_COMMAND_FAILED",
            "original Checker terminal consumer returned an invalid result",
        )
    return value


def _validate_incomplete_resume(request: Mapping[str, Any]) -> dict[str, Any]:
    required = {
        "schema_version", "method_version", "recovery_invocation_id", "run_id", "go_id", "cell_id",
        "attempt", "plan_revision", "runtime_revision", "token_sequence", "worker_role_instance_id",
        "checker_role_instance_id", "checker_endpoint_version", "checker_endpoint",
        "runtime_projection_path", "runtime_projection_sha256", "candidate_repository",
        "candidate_commit", "candidate_parent", "candidate_message_id", "payload_sha256",
        "candidate_submitted_event_id", "transport_started_event_id", "commit_request_path",
        "commit_request_sha256", "native_attempt_path", "checker_credential_path", "state_command",
        "transport_command", "immutable_sha256", "result_path", "background_path", "ocrv_session",
        "recovery_root",
    }
    partial = request.get('partial_review')
    if partial is not None:
        required.add('partial_review')
        from .partial_review import validate_partial_source
        try:
            validate_partial_source(request)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise CompletionError('CHECKER_INCOMPLETE_RESUME_EVIDENCE_INVALID', str(exc)) from exc
    try:
        checker = Endpoint.from_dict(request["checker_endpoint"])
        session = request["ocrv_session"]
        attempt = Path(str(request["native_attempt_path"])).resolve()
        recovery = Path(str(request["recovery_root"])).resolve()
        started_path = attempt / "started.json"
    except (KeyError, TypeError, ValueError) as exc:
        raise CompletionError("CHECKER_INCOMPLETE_RESUME_REQUEST_INVALID", "resume request is invalid") from exc
    if (
        set(request) != required or request.get("schema_version") != INCOMPLETE_RESUME_SCHEMA
        or request.get("method_version") != "4.3.6" or not isinstance(session, Mapping)
        or recovery != attempt / "resume-incomplete-checker" / str(request["recovery_invocation_id"])
        or Path(str(request["result_path"])).resolve() != recovery / "result.json"
        or (partial is None and any((attempt / name).exists() for name in ("completed.json", "failed.json", "ocrv-result.json")))
        or (recovery / "resume-consumed.json").exists()
        or session.get("diff_commit") != request.get("candidate_commit")
        or session.get("model") != "qwen3.8-max" or session.get("review_mode") != "commit"
        or (partial is None and (session.get("aborted") is not True or session.get("selected_files") != 0
        or session.get("completed_files") != 0))
    ):
        raise CompletionError("CHECKER_INCOMPLETE_RESUME_REQUEST_INVALID", "resume identity is invalid or already consumed")
    try:
        started = validate_native_start(
            started_path, adapter=checker.adapter, run_id=str(request["run_id"]),
            cell_id=str(request["cell_id"]), message_id=str(request["candidate_message_id"]),
            request_sha256=str(request["payload_sha256"]),
        )
    except NativeActivityError as exc:
        raise CompletionError("CHECKER_INCOMPLETE_RESUME_EVIDENCE_INVALID", "original OCRV start is invalid") from exc
    if inspect_native_activity(
        started_path, terminal_paths=() if partial is not None else (attempt / "completed.json", attempt / "failed.json"),
        **({'native_probe': lambda _start: {'status':'UNKNOWN'}} if partial is not None else {}),
    ).get("status") != "DEAD_WITHOUT_TERMINAL":
        raise CompletionError("CHECKER_INCOMPLETE_RESUME_EVIDENCE_INVALID", "original OCRV process is not dead")
    names = {"endpoint.json", "envelope.json", "started.json", "ocrv-request.json", "ocrv-preflight.json",
             "d1-background.md", "native-activity.json", "session-record"}
    paths = {name: attempt / name for name in names}
    paths["d1-background.md"] = Path(str(request["background_path"])).resolve()
    paths["session-record"] = Path(str(session.get("session_record_path", ""))).resolve()
    if partial is not None:
        paths['ocrv-request.json'] = attempt / 'review-segments/segment-001/request.json'
        paths['ocrv-preflight.json'] = attempt / 'review-segments/segment-001/preflight.json'
    immutable = request["immutable_sha256"]
    if not isinstance(immutable, Mapping) or set(immutable) != names or any(
        not path.is_file() or _sha256(path) != immutable.get(name) for name, path in paths.items()
    ) or session.get("session_record_sha256") != immutable.get("session-record"):
        raise CompletionError("CHECKER_INCOMPLETE_RESUME_EVIDENCE_INVALID", "resume input is missing")
    preflight = _read_object(paths["ocrv-preflight.json"], "OCRV preflight")
    if (preflight.get("status") != "READY" or preflight.get("request_sha256") != immutable["ocrv-request.json"]
        or not _matches(preflight.get("background"), {"sha256": immutable["d1-background.md"]})):
        raise CompletionError("CHECKER_INCOMPLETE_RESUME_EVIDENCE_INVALID", "OCRV preflight is not exact")
    source = {key: value for key, value in request.items() if key not in {"background_path", "ocrv_session", "recovery_root", 'partial_review'}}
    source.update({"schema_version": COMMITTED_TERMINAL_SCHEMA, "raw_review_path": "unused", "immutable_sha256": {name: immutable[name] for name in ("endpoint.json", "envelope.json", "started.json", "ocrv-request.json")}})
    return {**_validate_committed_terminal_request(source, source_only=True, partial_review=partial), "paths": paths, "session": dict(session), "recovery_root": recovery}
def resume_incomplete_checker(request_path: Path, *, request_sha256: str, prepare_only: bool = False) -> Mapping[str, Any]:
    data = request_path.read_bytes()
    if hashlib.sha256(data).hexdigest() != request_sha256:
        raise CompletionError("CHECKER_INCOMPLETE_RESUME_REQUEST_MISMATCH", "resume request hash mismatch")
    request = _read_object(request_path, "incomplete Checker resume request")
    validated = _validate_incomplete_resume(request)
    if prepare_only:
        return {'schema_version':'slk.ocrv-incomplete-checker-resume-preflight/v1',
                'status':'READY_FOR_SEALED_CHECKER_PREFLIGHT', 'request_sha256':request_sha256,
                **{key:request[key] for key in ('run_id','go_id','cell_id','attempt','candidate_message_id',
                    'runtime_revision','token_sequence','checker_role_instance_id','checker_endpoint_version')}}
    return _run_sealed_checker_terminal(
        request_path, request, validated["checker"], request_sha256=request_sha256,
        mode="--slk-resume-incomplete-checker", result_schema=COMMITTED_TERMINAL_RESULT_SCHEMA,
        error_code="CHECKER_INCOMPLETE_RESUME_COMMAND_FAILED",
    )
def _run_json_command(
    command: list[str],
    arguments: list[str],
    *,
    credential: str | None,
) -> dict[str, Any]:
    from .process import windows_no_window_kwargs

    environment = os.environ.copy()
    environment.pop("SLK_ROLE_CREDENTIAL", None)
    environment.pop("SLK_OVERWATCHER_CREDENTIAL", None)
    if credential is not None:
        environment["SLK_ROLE_CREDENTIAL"] = credential
    environment["PYTHONIOENCODING"] = "utf-8"
    environment["PYTHONUTF8"] = "1"
    completed = subprocess.run(
        command + arguments,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        check=False,
        env=environment,
        **windows_no_window_kwargs(),
    )
    decoded: dict[str, str] = {}
    for label, raw in (("stdout", completed.stdout), ("stderr", completed.stderr)):
        data = raw if isinstance(raw, bytes) else b"" if raw is None else None
        if data is None:
            raise CompletionError(
                "WORKER_CONTINUATION_COMMAND_ENCODING_INVALID",
                f"continuation command {label} did not return bytes",
            )
        try:
            decoded[label] = data.decode("utf-8")
        except UnicodeDecodeError as exc:
            digest = hashlib.sha256(data).hexdigest()
            raise CompletionError(
                "WORKER_CONTINUATION_COMMAND_ENCODING_INVALID",
                f"continuation command {label} is not UTF-8; sha256={digest}",
            ) from exc
    parsed: tuple[dict[str, Any], str] | None = None
    last_error: json.JSONDecodeError | None = None
    for raw, parse_status in (
        (decoded["stdout"], "PARSED_STDOUT"),
        (decoded["stderr"], "PARSED_STDERR"),
    ):
        if not raw.strip():
            continue
        try:
            candidate = json.loads(raw.strip())
        except json.JSONDecodeError as exc:
            last_error = exc
            continue
        if not isinstance(candidate, dict):
            raise CompletionError(
                "WORKER_CONTINUATION_COMMAND_FAILED", "continuation command JSON must be an object"
            )
        parsed = (dict(candidate), parse_status)
        break
    if parsed is None:
        raise CompletionError(
            "WORKER_CONTINUATION_COMMAND_FAILED", "continuation command returned no parseable JSON"
        ) from last_error
    value, parse_status = parsed
    if "_slk_command" in value:
        raise CompletionError(
            "WORKER_CONTINUATION_COMMAND_FAILED", "continuation command used a reserved result field"
        )
    business_status = value.get("verdict", value.get("status"))
    value["_slk_command"] = {
        "process_exit": completed.returncode,
        "json_parse": parse_status,
        "business_status": business_status if isinstance(business_status, str) else None,
    }
    return value


def execute_worker_continuation(request: Mapping[str, Any]) -> dict[str, Any]:
    """Run the continuation inside the resumed DSH process using its own DPAPI credential."""

    if os.environ.get("SLK_DSH_INSTANCE_ID") != request.get("worker_instance_id") or os.environ.get(
        "SLK_DSH_SESSION_ID"
    ) != request.get("worker_session_id"):
        raise CompletionError(
            "WORKER_CONTINUATION_SESSION_MISMATCH",
            "continuation is not running inside the exact resumed DSH Worker Session",
        )
    state_command = list(request["state_command"])
    credential = unprotect_dpapi_hex(str(request["credential_path"]))
    request_root = _continuation_root(request)
    request_root.mkdir(parents=True, exist_ok=True)

    def state_request(command_name: str, value: Mapping[str, Any]) -> dict[str, Any]:
        path = request_root / f"{command_name}-{value.get('event_id', value.get('transport_receipt_id', 'request'))}.json"
        _write_or_reuse_stable_request(path, value)
        return _run_json_command(state_command, [command_name, "--request", str(path)], credential=credential)

    def authenticate(run_id: str, role_instance_id: str) -> int:
        value = _run_json_command(
            state_command,
            ["authenticate-role", "--run-id", run_id, "--role-instance-id", role_instance_id],
            credential=credential,
        )
        if value.get("role_instance_id") != role_instance_id or value.get("role") != "worker":
            raise CompletionError("WORKER_CREDENTIAL_MISMATCH", "credential is not the active Worker")
        revision = value.get("runtime_revision")
        if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
            raise CompletionError("WORKER_RUNTIME_REVISION_INVALID", "fresh runtime revision is unavailable")
        return revision

    def write_event(value: dict[str, Any]) -> str:
        return str(state_request("write", value).get("status"))

    checker_attempt_root = request_root / "checker-attempts"

    def start_checker(endpoint_raw: dict[str, Any], envelope_raw: dict[str, Any]) -> Mapping[str, Any]:
        endpoint_path = request_root / "checker-endpoint.json"
        envelope_path = request_root / "candidate-envelope.json"
        for path, value in ((endpoint_path, endpoint_raw), (envelope_path, envelope_raw)):
            encoded = (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
            if path.exists() and path.read_bytes() != encoded:
                raise CompletionError("WORKER_CONTINUATION_CONFLICT", f"immutable delivery conflicts: {path.name}")
            if not path.exists():
                path.write_bytes(encoded)
        return {
            "status": "delivery_ready",
            "endpoint_path": str(endpoint_path),
            "envelope_path": str(envelope_path),
            "attempt_root": str(checker_attempt_root),
        }

    def commit_start(_value: dict[str, Any]) -> Mapping[str, Any]:
        raise CompletionError(
            "CHECKER_START_HOST_INVALID",
            "a DSH Worker process cannot host or commit the OCRV Checker start",
        )

    try:
        return run_worker_continuation(
            request,
            authenticate=authenticate,
            write_event=write_event,
            start_checker=start_checker,
            commit_start=commit_start,
            defer_checker_start=True,
        )
    finally:
        credential = ""
