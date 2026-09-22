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


INSPECTION_SCHEMA = "slk.worker-completion-inspection/v1"
CONTINUATION_SCHEMA = "slk.worker-continuation/v1"
CHECKER_RECOVERY_SCHEMA = "slk.ocrv-worker-recovery-request/v1"
CHECKER_RECOVERY_RESULT_SCHEMA = "slk.ocrv-worker-recovery-result/v1"
_NAMESPACE = uuid.UUID("23c8316f-29fe-4f2f-b5c5-90ba4e7b1224")


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
    result = _read_object(result_path, "Worker result")
    completed = _read_object(completed_path, "Worker terminal result")
    attempt_number = _source_attempt(runtime_projection, envelope)
    snapshot = runtime_projection.get("runtime_snapshot")
    session_id = started.get("session_id")
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
        or completed.get("status") != "completed"
        or result.get("status") != "completed"
        or result.get("message_id") != envelope.message_id
        or result.get("role_instance_id") != endpoint.role_instance_id
        or not isinstance(snapshot, Mapping)
        or snapshot.get("method_version") != "4.2.5"
        or snapshot.get("plan_revision") != plan_revision
        or snapshot.get("runtime_revision") != runtime_revision
        or snapshot.get("token_sequence") != token_sequence
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
        "method_version": "4.2.5",
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
        "worker_result_sha256": _sha256(result_path),
        "worker_role_instance_id": endpoint.role_instance_id,
        "worker_instance_id": str(endpoint.address["instance_id"]),
        "worker_session_id": session_id,
        "checker_endpoint": dict(checker_endpoint_raw),
        "credential_path": str(credential),
        "state_command": list(state_command),
        "transport_command": list(transport_command),
        "token_sequence": token_sequence,
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
    if result.get("status") != "CHECKER_STARTED" or result.get("source_message_id") != request.get(
        "source_message_id"
    ):
        raise CompletionError("WORKER_CONTINUATION_RESULT_INVALID", "continuation result does not prove the handoff")
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
    d1_started = bool(event_types & {"D1_STARTED", "D1_INCOMPLETE", "D1_FAILED", "D1_PASSED"})
    base = {
        "schema_version": INSPECTION_SCHEMA,
        "run_id": envelope.run_id,
        "go_id": envelope.go_id,
        "cell_id": envelope.cell_id,
        "attempt": attempt_number,
        "source_message_id": envelope.message_id,
        "worker_role_instance_id": endpoint.role_instance_id,
        "observed_at": observed_at,
        "cadence_seconds": cadence_seconds,
        "anomaly_codes": [],
        "notification_already_sent": False,
        "missing_worker_events": [],
    }
    if not completed:
        return {**base, "status": "IN_PROGRESS", "grace_started_at": None}
    if token_owner != endpoint.role_instance_id or d1_started:
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
            {"WORK_STARTED", "D0_COMPLETED", "CANDIDATE_SUBMITTED"} - event_types
        ),
    }


Authenticate = Callable[[str, str], int]
WriteEvent = Callable[[dict[str, Any]], str]
StartChecker = Callable[[dict[str, Any], dict[str, Any]], Mapping[str, Any]]
CommitStart = Callable[[dict[str, Any]], str]


def run_worker_continuation(
    request: Mapping[str, Any],
    *,
    authenticate: Authenticate,
    write_event: WriteEvent,
    start_checker: StartChecker,
    commit_start: CommitStart,
) -> dict[str, Any]:
    """Execute the bounded Worker-owned D0/candidate/checker handoff suffix."""

    if request.get("schema_version") != CONTINUATION_SCHEMA or request.get("method_version") != "4.2.5":
        raise CompletionError("WORKER_CONTINUATION_INVALID", "continuation contract version is invalid")
    run_id = str(request["run_id"])
    role_instance_id = str(request["worker_role_instance_id"])
    authenticate(run_id, role_instance_id)
    attempt = Path(str(request["source_attempt_root"]))
    result_path = attempt / "worker-result.json"
    if _sha256(result_path) != request.get("worker_result_sha256"):
        raise CompletionError("WORKER_COMPLETION_EVIDENCE_INVALID", "Worker result hash changed")
    worker_result = _read_object(result_path, "Worker result")
    source_envelope = Envelope.from_dict(_read_object(attempt / "envelope.json", "Worker envelope"))
    next_payload = worker_result.get("next_payload")
    if not isinstance(next_payload, Mapping):
        raise CompletionError("WORKER_COMPLETION_EVIDENCE_INVALID", "Worker next_payload is invalid")
    source_message_id = str(request["source_message_id"])
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
        ("candidate-submitted", "CANDIDATE_SUBMITTED", {"candidate": worker_result["candidate"], "checker_endpoint_version": request["checker_endpoint"]["endpoint_version"]}),
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
    cell_goal = next_payload.get("cell_goal", source_envelope.payload.get("cell_goal"))
    d1_criteria = source_envelope.payload.get("d1_criteria")
    evidence_files = [
        str(path.resolve())
        for path in (
            attempt / "worker-result.json",
            attempt / "completed.json",
            attempt / "native.stdout.txt",
            attempt / "native.stderr.txt",
        )
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
        "message_id": _stable_id(source_message_id, "candidate-ready"),
        "token_sequence": int(request["token_sequence"]) + 1,
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
    commit_start(commit_request)
    return {
        "status": "CHECKER_STARTED",
        "run_id": run_id,
        "source_message_id": source_message_id,
        "candidate_message_id": envelope["message_id"],
    }


def _decode_dpapi_plaintext(plain: bytes) -> str:
    """Decode only the two credential encodings produced by supported SLK provisioners."""

    try:
        if plain.startswith(b"s\x00l\x00k\x00_\x00") and len(plain) % 2 == 0:
            secret = plain.decode("utf-16-le")
        elif plain.startswith(b"slk_"):
            secret = plain.decode("utf-8")
        else:
            raise CompletionError(
                "WORKER_CREDENTIAL_UNAVAILABLE", "Worker credential plaintext is invalid"
            )
    except UnicodeDecodeError as exc:
        raise CompletionError("WORKER_CREDENTIAL_UNAVAILABLE", "Worker credential plaintext is invalid") from exc
    if secret.endswith("\0"):
        secret = secret[:-1]
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


def execute_checker_recovery(
    request: Mapping[str, Any],
    *,
    request_sha256: str,
    authenticate_checker: CheckerAuthenticate = _default_checker_authenticate,
    resume_continuation: ResumeContinuation = resume_worker_continuation,
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
    if request.get("method_version") != "4.2.5":
        raise CompletionError("CHECKER_RECOVERY_REQUEST_INVALID", "Checker recovery requires SLK 4.2.5")
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
    outcome = resume_continuation(continuation)
    if outcome.get("status") != "CHECKER_STARTED":
        raise CompletionError("CHECKER_RECOVERY_FAILED", "Worker continuation did not start Checker D1")
    return {
        "schema_version": CHECKER_RECOVERY_RESULT_SCHEMA,
        "method_version": "4.2.5",
        "status": "CHECKER_STARTED",
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
    text = completed.stdout.strip() if completed.returncode == 0 else completed.stderr.strip()
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise CompletionError("WORKER_CONTINUATION_COMMAND_FAILED", "continuation command returned non-JSON") from exc
    if completed.returncode != 0 or not isinstance(value, dict):
        raise CompletionError(
            "WORKER_CONTINUATION_COMMAND_FAILED",
            str(value.get("message", "continuation command failed")) if isinstance(value, dict) else "continuation command failed",
        )
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
    transport_command = list(request["transport_command"])
    credential = unprotect_dpapi_hex(str(request["credential_path"]))
    request_root = Path(str(request["source_attempt_root"])) / "worker-continuation"
    request_root.mkdir(parents=True, exist_ok=True)

    def state_request(command_name: str, value: Mapping[str, Any]) -> dict[str, Any]:
        path = request_root / f"{command_name}-{value.get('event_id', value.get('transport_receipt_id', 'request'))}.json"
        encoded = (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
        if path.exists() and path.read_bytes() != encoded:
            raise CompletionError("WORKER_CONTINUATION_CONFLICT", f"immutable request conflicts: {path.name}")
        if not path.exists():
            temporary = path.with_suffix(path.suffix + ".tmp")
            temporary.write_bytes(encoded)
            temporary.replace(path)
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
        message_id = str(envelope_raw["message_id"])
        started_path = checker_attempt_root / str(envelope_raw["run_id"]) / message_id / "started.json"
        if started_path.is_file():
            status = "already_started"
        else:
            result = _run_json_command(
                transport_command,
                [
                    "send",
                    "--endpoint",
                    str(endpoint_path),
                    "--envelope",
                    str(envelope_path),
                    "--attempt-root",
                    str(checker_attempt_root),
                ],
                credential=None,
            )
            status = str(result.get("status"))
        return {
            "status": status,
            "started_path": str(started_path),
            "endpoint_path": str(
                checker_attempt_root / str(envelope_raw["run_id"]) / message_id / "endpoint.json"
            ),
            "envelope_path": str(
                checker_attempt_root / str(envelope_raw["run_id"]) / message_id / "envelope.json"
            ),
        }

    def commit_start(value: dict[str, Any]) -> str:
        return str(state_request("commit-delivery-start", value).get("status"))

    try:
        return run_worker_continuation(
            request,
            authenticate=authenticate,
            write_event=write_event,
            start_checker=start_checker,
            commit_start=commit_start,
        )
    finally:
        credential = ""
