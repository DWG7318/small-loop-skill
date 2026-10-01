"""Bounded Worker-completion continuation and read-only handoff inspection."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import time
import uuid
import ctypes
from ctypes import wintypes
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

from .contracts import ENVELOPE_SCHEMA, Endpoint, Envelope, canonical_json_sha256
from .native_activity import NativeActivityError, validate_native_start
from .task_file import TaskFileError, verify_task_file


INSPECTION_SCHEMA = "slk.worker-completion-inspection/v1"
CONTINUATION_SCHEMA = "slk.worker-continuation/v1"
CHECKER_RECOVERY_SCHEMA = "slk.ocrv-worker-recovery-request/v1"
CHECKER_RECOVERY_RESULT_SCHEMA = "slk.ocrv-worker-recovery-result/v1"
_NAMESPACE = uuid.UUID("23c8316f-29fe-4f2f-b5c5-90ba4e7b1224")
_LEGACY_WORKER_START_FIELDS = frozenset(
    {"instance_id", "message_id", "run_id", "session_id", "status", "task_sha256"}
)


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
            and task.get("result_contract") == DshAdapter().result_contract(endpoint, envelope)
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
    else:
        raise CompletionError(
            "WORKER_CONTINUATION_NOT_READY",
            "Worker attempt has neither a completed result nor the exact recoverable missing-result terminal",
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
        "continuation_result_path": str(attempt / "worker-continuation" / "result.json"),
        "source_endpoint_sha256": _sha256(endpoint_path),
        "source_envelope_sha256": _sha256(envelope_path),
        "recovery_mode": recovery_mode,
        "worker_result_path": str(continuation_result_path.resolve()),
        "worker_result_sha256": worker_result_sha256,
        "source_terminal_sha256": _sha256(source_terminal_path),
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


def resume_worker_continuation(request: Mapping[str, Any]) -> dict[str, Any]:
    """Resume exactly the recorded DSH Session and let it execute one bounded suffix."""

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
    terminal_path = attempt / ("failed.json" if recovery_mode == "MISSING_RESULT" else "completed.json")
    if recovery_mode not in {"COMPLETED_RESULT", "MISSING_RESULT"} or (
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
    continuation_root = attempt / "worker-continuation"
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
            "schema_version, message_id, run_id, role_instance_id, status, candidate, next_payload, and blocker; "
            "status must be completed, blocker must be null, and the identity must match the source attempt. "
            "After writing it, execute the request's transport_command with "
            f"`continue-worker --request {json.dumps(str(request_path))} --sha256 {digest}`. "
            "Do not read, print, copy, or return credential plaintext.\n"
            f"<slk-worker-continuation-task path={json.dumps(str(request_path))} sha256={json.dumps(digest)} />"
        )
    else:
        instruction = (
            "Resume this exact SLK Worker Session only to finish its already-completed CELL handoff. "
            "Verify the immutable request SHA-256, then execute its transport_command with "
            f"`continue-worker --request {json.dumps(str(request_path))} --sha256 {digest}`. "
            "Do not read, print, copy, or return credential plaintext.\n"
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

    if request.get("schema_version") != CONTINUATION_SCHEMA or request.get("method_version") != "4.3.6":
        raise CompletionError("WORKER_CONTINUATION_INVALID", "continuation contract version is invalid")
    run_id = str(request["run_id"])
    role_instance_id = str(request["worker_role_instance_id"])
    authenticate(run_id, role_instance_id)
    attempt = Path(str(request["source_attempt_root"]))
    recovery_mode = request.get("recovery_mode")
    if recovery_mode not in {"COMPLETED_RESULT", "MISSING_RESULT"}:
        raise CompletionError("WORKER_CONTINUATION_INVALID", "continuation recovery mode is invalid")
    result_path = Path(str(request.get("worker_result_path", ""))).resolve()
    expected_result_path = (
        attempt / "worker-continuation" / "recovered-worker-result.json"
        if recovery_mode == "MISSING_RESULT"
        else attempt / "worker-result.json"
    ).resolve()
    if result_path != expected_result_path:
        raise CompletionError("WORKER_COMPLETION_EVIDENCE_INVALID", "Worker result path is not exact")
    if recovery_mode == "COMPLETED_RESULT":
        if (
            request.get("worker_result_sha256") is None
            or _sha256(result_path) != request.get("worker_result_sha256")
            or _sha256(attempt / "completed.json") != request.get("source_terminal_sha256")
        ):
            raise CompletionError("WORKER_COMPLETION_EVIDENCE_INVALID", "Worker result hash changed")
    elif (
        request.get("worker_result_sha256") is not None
        or _missing_result_failure(attempt, Envelope.from_dict(_read_object(attempt / "envelope.json", "Worker envelope"))) is None
        or _sha256(attempt / "failed.json") != request.get("source_terminal_sha256")
    ):
        raise CompletionError(
            "WORKER_COMPLETION_EVIDENCE_INVALID",
            "missing-result recovery source is not exact",
        )
    worker_result = _read_object(result_path, "Worker result")
    endpoint_path = attempt / "endpoint.json"
    source_endpoint = Endpoint.from_dict(_read_object(endpoint_path, "Worker endpoint"))
    if (
        _sha256(endpoint_path) != request.get("source_endpoint_sha256")
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
    valid_result_fields = {frozenset(completed_result_fields | {"blocker"})}
    if recovery_mode == "COMPLETED_RESULT":
        valid_result_fields.add(frozenset(completed_result_fields))
    if (
        frozenset(worker_result) not in valid_result_fields
        or worker_result.get("schema_version") != "slk.worker-result/v1"
        or worker_result.get("message_id") != request.get("source_message_id")
        or worker_result.get("run_id") != run_id
        or worker_result.get("role_instance_id") != role_instance_id
        or worker_result.get("status") != "completed"
        or not isinstance(worker_result.get("candidate"), Mapping)
        or not isinstance(next_payload, Mapping)
        or ("blocker" in worker_result and worker_result.get("blocker") is not None)
    ):
        raise CompletionError("WORKER_COMPLETION_EVIDENCE_INVALID", "Worker next_payload is invalid")
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
    for suffix, event_type, details in (
        ("work-started", "WORK_STARTED", {"source_message_id": source_message_id, "resumed_session_id": request["worker_session_id"]}),
        (
            "d0-completed",
            "D0_COMPLETED",
            {
                "candidate": worker_result["candidate"],
                "d0": next_payload.get("d0"),
                "changed_paths": next_payload.get("changed_paths", []),
                "unproved": next_payload.get("unproved", []),
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
    fresh_runtime_revision = authenticate(run_id, role_instance_id)
    if isinstance(fresh_runtime_revision, bool) or not isinstance(fresh_runtime_revision, int) or fresh_runtime_revision < 1:
        raise CompletionError("WORKER_RUNTIME_REVISION_INVALID", "fresh runtime revision is unavailable")
    repository = next_payload.get("candidate_repository", next_payload.get("repository"))
    if repository is None:
        repository = source_endpoint.address.get("cwd")
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
    source_terminal_path = attempt / ("failed.json" if recovery_mode == "MISSING_RESULT" else "completed.json")
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
    evidence_index_path = attempt / "worker-continuation" / "checker-evidence-index.json"
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
        not isinstance(repository, str)
        or not Path(repository).is_absolute()
        or not Path(repository).is_dir()
        or not isinstance(cell_goal, str)
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
        "repository": str(Path(repository).resolve()),
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
            "runtime_revision": fresh_runtime_revision,
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
        "expected_runtime_revision": fresh_runtime_revision,
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
        or committed_revision <= fresh_runtime_revision
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


def _activate_staged_checker(
    outcome: Mapping[str, Any],
    continuation: Mapping[str, Any],
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
        committed = _run_json_command(
            list(continuation["state_command"]),
            ["commit-delivery-start", "--request", str(_write_or_reuse_stable_request(
                Path(str(continuation["source_attempt_root"]))
                / "worker-continuation"
                / f"commit-delivery-start-{commit_request['transport_receipt_id']}.json",
                commit_request,
            ))],
            credential=worker_credential,
        )
    finally:
        worker_credential = ""
    committed_revision = committed.get("runtime_revision")
    if (
        committed.get("status") not in {"committed", "idempotent_replay"}
        or isinstance(committed_revision, bool)
        or not isinstance(committed_revision, int)
        or committed_revision <= staged_revision
        or committed.get("token_sequence") != envelope.token_sequence
        or committed.get("message_id") != envelope.message_id
    ):
        raise CompletionError("WORKER_RUNTIME_REVISION_INVALID", "Checker start commit is not exact")
    return {
        "status": "CHECKER_STARTED",
        "runtime_revision": committed_revision,
        "token_sequence": envelope.token_sequence,
        "candidate_message_id": envelope.message_id,
        "checker_token_already_committed": False,
        "native_attempt_path": str(attempt),
    }


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
            "corrects_event_id": None,
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
        write_checker_event(
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
                or review.get("exit_code") != expected_exit_code
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
        write_checker_event(event_type, "d1-result-v2", details, occurred_at)
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
    if (
        authentication.get("status") != "authenticated"
        or authentication.get("role") != "checker"
        or authentication.get("role_instance_id") != role_instance_id
        or authentication.get("runtime_revision") != request.get("runtime_revision")
    ):
        raise CompletionError(
            "CHECKER_RECOVERY_AUTHENTICATION_FAILED",
            "credential does not prove the current Checker at the requested runtime revision",
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
    completed = subprocess.run(
        command + arguments,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        env=environment,
        **windows_no_window_kwargs(),
    )
    parsed: tuple[dict[str, Any], str] | None = None
    last_error: json.JSONDecodeError | None = None
    for raw, parse_status in (
        (completed.stdout, "PARSED_STDOUT"),
        (completed.stderr, "PARSED_STDERR"),
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
    request_root = Path(str(request["source_attempt_root"])) / "worker-continuation"
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
