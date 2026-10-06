"""Closed native-start evidence and read-only activity inspection."""

from __future__ import annotations

import ctypes
import errno
import hashlib
import json
import os
import re
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

from .contracts import ContractError, DeliveryResult


START_SCHEMA = "slk.native-start/v2"
ACTIVITY_SCHEMA = "slk.native-activity/v1"
TASK_ACTIVITY_SCHEMA = "slk.native-task-activity/v1"
START_FIELDS = frozenset(
    {
        "schema_version",
        "status",
        "adapter",
        "run_id",
        "cell_id",
        "message_id",
        "request_sha256",
        "native_request_sha256",
        "observed_at",
        "process",
        "native_task",
    }
)
PROCESS_FIELDS = frozenset({"pid", "creation_time"})
TASK_FIELDS = frozenset({"kind", "id", "status"})
ACTIVITY_FIELDS = frozenset(
    {
        "schema_version",
        "adapter",
        "run_id",
        "cell_id",
        "message_id",
        "native_task_id",
        "status",
        "sequence",
        "observed_at",
        "last_event",
        "waiting_on",
    }
)
SHA256 = re.compile(r"^[0-9a-f]{64}$")
NATIVE_START_STATUSES = frozenset({"RUNNING", "PENDING", "IDLE"})
PLATFORM_ACTIVITY_TASK_KINDS = frozenset({"codex-desktop-turn"})


class NativeActivityError(ValueError):
    """Native evidence is absent, stale, mismatched, or malformed."""


class ProcessMissingError(NativeActivityError):
    """The operating system positively confirmed that a process is absent."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(value, stream, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        for attempt in range(3):
            try:
                os.replace(temporary_name, path)
                break
            except OSError as exc:
                if exc.errno not in {errno.EBUSY, errno.EPERM} or attempt == 2:
                    raise
                time.sleep(0.01 * (attempt + 1))
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)


def process_creation_time(pid: int) -> str:
    """Return an OS identity value that changes when a PID is reused."""

    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
        raise NativeActivityError("native process pid must be a positive integer")
    if os.name == "nt":
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.restype = ctypes.c_void_p
        handle = kernel32.OpenProcess(0x1000, False, pid)
        if not handle:
            error = ctypes.get_last_error()
            if error == 87:  # ERROR_INVALID_PARAMETER: no process has this PID.
                raise ProcessMissingError("native process does not exist")
            raise NativeActivityError(f"native process is not queryable (winerror={error})")
        try:
            created = ctypes.c_ulonglong()
            exited = ctypes.c_ulonglong()
            kernel = ctypes.c_ulonglong()
            user = ctypes.c_ulonglong()
            if not kernel32.GetProcessTimes(
                handle,
                ctypes.byref(created),
                ctypes.byref(exited),
                ctypes.byref(kernel),
                ctypes.byref(user),
            ):
                raise NativeActivityError("native process creation time is unavailable")
            if exited.value:
                raise ProcessMissingError('native process has exited; retained handle is not liveness')
            return f"win-filetime:{created.value}"
        finally:
            kernel32.CloseHandle(handle)
    stat = Path(f"/proc/{pid}/stat")
    try:
        fields = stat.read_text(encoding="ascii").split()
    except FileNotFoundError as exc:
        raise ProcessMissingError("native process does not exist") from exc
    if len(fields) > 21:
        return f"proc-start:{fields[21]}"
    raise NativeActivityError("native process creation time is unavailable")


def process_probe(pid: int, creation_time: str) -> dict[str, bool]:
    try:
        current = process_creation_time(pid)
    except ProcessMissingError:
        return {"exists": False, "identity_matches": False}
    return {"exists": True, "identity_matches": current == creation_time}


def make_native_start(
    *,
    adapter: str,
    run_id: str,
    cell_id: str,
    message_id: str,
    request_sha256: str,
    native_request_sha256: str,
    native_task_kind: str,
    native_task_id: str,
    native_task_status: str,
    pid: int,
    observed_at: str | None = None,
) -> dict[str, Any]:
    value = {
        "schema_version": START_SCHEMA,
        "status": "STARTED",
        "adapter": adapter,
        "run_id": run_id,
        "cell_id": cell_id,
        "message_id": message_id,
        "request_sha256": request_sha256,
        "native_request_sha256": native_request_sha256,
        "observed_at": observed_at or utc_now(),
        "process": {"pid": pid, "creation_time": process_creation_time(pid)},
        "native_task": {
            "kind": native_task_kind,
            "id": native_task_id,
            "status": native_task_status,
        },
    }
    _validate_start_value(value)
    return value


def write_native_start(path: Path, value: Mapping[str, Any]) -> None:
    _validate_start_value(value)
    _atomic_json(path, value)


def _nonempty(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise NativeActivityError(f"{label} must be one canonical non-empty string")
    return value


def _validate_start_value(value: Mapping[str, Any]) -> dict[str, Any]:
    if set(value) != START_FIELDS or value.get("schema_version") != START_SCHEMA:
        raise NativeActivityError("native start must use the closed slk.native-start/v2 contract")
    if value.get("status") != "STARTED":
        raise NativeActivityError("native start status must be STARTED")
    for name in ("adapter", "run_id", "cell_id", "message_id", "observed_at"):
        _nonempty(value.get(name), name)
    for digest_name in ("request_sha256", "native_request_sha256"):
        digest = value.get(digest_name)
        if not isinstance(digest, str) or not SHA256.fullmatch(digest):
            raise NativeActivityError(f"{digest_name} must be one lowercase SHA-256")
    process = value.get("process")
    if not isinstance(process, Mapping) or set(process) != PROCESS_FIELDS:
        raise NativeActivityError("native start process identity is incomplete")
    pid = process.get("pid")
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
        raise NativeActivityError("native start pid must be a positive integer")
    _nonempty(process.get("creation_time"), "process.creation_time")
    task = value.get("native_task")
    if not isinstance(task, Mapping) or set(task) != TASK_FIELDS:
        raise NativeActivityError("native task identity is incomplete")
    _nonempty(task.get("kind"), "native_task.kind")
    _nonempty(task.get("id"), "native_task.id")
    if task.get("status") not in NATIVE_START_STATUSES:
        raise NativeActivityError("native task start status is not allowed")
    return dict(value)


def validate_native_start(
    path: Path,
    *,
    adapter: str | None = None,
    run_id: str | None = None,
    cell_id: str | None = None,
    message_id: str | None = None,
    request_sha256: str | None = None,
    native_request_sha256: str | None = None,
) -> dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise NativeActivityError("native start evidence is unreadable") from exc
    if not isinstance(raw, Mapping):
        raise NativeActivityError("native start evidence must be an object")
    value = _validate_start_value(raw)
    expected = {
        "adapter": adapter,
        "run_id": run_id,
        "cell_id": cell_id,
        "message_id": message_id,
        "request_sha256": request_sha256,
        "native_request_sha256": native_request_sha256,
    }
    for name, wanted in expected.items():
        if wanted is not None and value[name] != wanted:
            raise NativeActivityError(f"native start {name} does not match the exact delivery")
    return value


def _file_native_probe(started_path: Path, start: Mapping[str, Any]) -> Mapping[str, Any]:
    activity_path = started_path.with_name("native-activity.json")
    if not activity_path.is_file():
        return {"status": "UNKNOWN", "error": "NATIVE_ACTIVITY_MISSING"}
    value = json.loads(activity_path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, Mapping):
        raise NativeActivityError("native activity projection is invalid")
    return value


def _current_native_start(started_path: Path, start: Mapping[str, Any]) -> tuple[Path, dict[str, Any]]:
    """Select the newest proven OCRV segment without rewriting the first start receipt."""

    if start["adapter"] != "ocrv-checker" or start["native_task"]["kind"] != "ocrv-review":
        return started_path, dict(start)
    candidates = sorted(started_path.parent.glob("review-segments/segment-*/started.json"))
    if not candidates:
        return started_path, dict(start)
    current_path = candidates[-1]
    current = validate_native_start(
        current_path,
        adapter=str(start["adapter"]),
        run_id=str(start["run_id"]),
        cell_id=str(start["cell_id"]),
        message_id=str(start["message_id"]),
        request_sha256=str(start["request_sha256"]),
    )
    if current["native_task"]["kind"] != "ocrv-review":
        raise NativeActivityError("current OCRV segment native task kind is invalid")
    return current_path, current


def validate_native_task_activity(
    value: Mapping[str, Any],
    *,
    adapter: str,
    run_id: str,
    cell_id: str,
    message_id: str,
    native_task_id: str | None = None,
    observed_at: str | None = None,
    max_activity_age_seconds: int = 300,
) -> dict[str, Any]:
    if set(value) != ACTIVITY_FIELDS or value.get("schema_version") != TASK_ACTIVITY_SCHEMA:
        raise NativeActivityError("native activity must use the closed task projection")
    expected = {
        "adapter": adapter,
        "run_id": run_id,
        "cell_id": cell_id,
        "message_id": message_id,
    }
    if any(value.get(name) != wanted for name, wanted in expected.items()):
        raise NativeActivityError("native activity identity does not match the exact delivery")
    task_id = _nonempty(value.get("native_task_id"), "native_task_id")
    if native_task_id is not None and task_id != native_task_id:
        raise NativeActivityError("native activity task identity does not match")
    if value.get("status") not in {"RUNNING", "PENDING", "IDLE", "COMPLETED", "FAILED"}:
        raise NativeActivityError("native activity status is invalid")
    sequence = value.get("sequence")
    if not isinstance(sequence, int) or isinstance(sequence, bool) or sequence < 0:
        raise NativeActivityError("native activity sequence is invalid")
    event = value.get("last_event")
    if (
        not isinstance(event, Mapping)
        or not isinstance(event.get("kind"), str)
        or not event.get("kind")
        or event.get("sequence") != sequence
    ):
        raise NativeActivityError("native activity event is invalid")
    tail = event.get("tail")
    if tail is not None:
        if not isinstance(tail, list) or len(tail) > 12:
            raise NativeActivityError("native activity tail must contain at most twelve events")
        previous_sequence = -1
        for item in tail:
            if not isinstance(item, Mapping) or set(item) != {
                "kind", "sequence", "observed_at", "detail_sha256"
            }:
                raise NativeActivityError("native activity tail must be metadata-only")
            item_sequence = item.get("sequence")
            detail_sha256 = item.get("detail_sha256")
            if (
                not isinstance(item.get("kind"), str)
                or not item["kind"]
                or not isinstance(item_sequence, int)
                or isinstance(item_sequence, bool)
                or item_sequence <= previous_sequence
                or item_sequence > sequence
                or not isinstance(item.get("observed_at"), str)
                or not isinstance(detail_sha256, str)
                or not SHA256.fullmatch(detail_sha256)
            ):
                raise NativeActivityError("native activity tail metadata is invalid")
            try:
                datetime.fromisoformat(str(item["observed_at"]).replace("Z", "+00:00"))
            except ValueError as exc:
                raise NativeActivityError("native activity tail timestamp is invalid") from exc
            previous_sequence = item_sequence
        if tail and tail[-1]["sequence"] != sequence:
            raise NativeActivityError("native activity tail must end at the current sequence")
    waiting_on = value.get("waiting_on")
    if waiting_on is not None and (
        not isinstance(waiting_on, str) or not waiting_on or waiting_on != waiting_on.strip()
    ):
        raise NativeActivityError("native activity waiting_on is invalid")
    if not isinstance(max_activity_age_seconds, int) or max_activity_age_seconds <= 0:
        raise NativeActivityError("max activity age must be positive seconds")
    observed = observed_at or utc_now()
    try:
        observed_time = datetime.fromisoformat(observed.replace("Z", "+00:00"))
        activity_time = datetime.fromisoformat(
            _nonempty(value.get("observed_at"), "observed_at").replace("Z", "+00:00")
        )
    except ValueError as exc:
        raise NativeActivityError("native activity timestamp is invalid") from exc
    age = (observed_time - activity_time).total_seconds()
    if age > max_activity_age_seconds:
        raise NativeActivityError("native activity is stale")
    if age < -1:
        raise NativeActivityError("native activity is from the future")
    return dict(value)


def _inspect_native_projection(
    start: Mapping[str, Any],
    native_probe: Callable[[Mapping[str, Any]], Mapping[str, Any]],
    observed: str | None,
    max_activity_age_seconds: int,
) -> tuple[dict[str, Any], str, str | None, str]:
    try:
        native = dict(native_probe(start))
        validation_observed = observed or utc_now()
        native_error = native.get("error")
        if native_error is not None:
            return native, "UNKNOWN", str(native_error), validation_observed
        validate_native_task_activity(
            native,
            adapter=str(start["adapter"]),
            run_id=str(start["run_id"]),
            cell_id=str(start["cell_id"]),
            message_id=str(start["message_id"]),
            native_task_id=str(start["native_task"]["id"]),
            observed_at=validation_observed,
            max_activity_age_seconds=max_activity_age_seconds,
        )
        mapped = {
            "RUNNING": "ACTIVE",
            "PENDING": "PENDING",
            "IDLE": "IDLE",
            "COMPLETED": "COMPLETED_WITHOUT_TERMINAL",
            "FAILED": "FAILED_WITHOUT_TERMINAL",
        }.get(str(native.get("status")), "UNKNOWN")
        return (
            native,
            mapped,
            None if mapped != "UNKNOWN" else "NATIVE_STATUS_UNKNOWN",
            validation_observed,
        )
    except NativeActivityError as exc:
        detail = str(exc)
        if "stale" in detail:
            error = "NATIVE_ACTIVITY_STALE"
        elif "future" in detail:
            error = "NATIVE_ACTIVITY_FROM_FUTURE"
        elif "identity" in detail:
            error = "NATIVE_ACTIVITY_IDENTITY_MISMATCH"
        else:
            error = "NATIVE_QUERY_FAILED"
        return {"last_event": None, "waiting_on": None}, "UNKNOWN", error, observed or utc_now()
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return (
            {"last_event": None, "waiting_on": None},
            "UNKNOWN",
            "NATIVE_QUERY_FAILED",
            observed or utc_now(),
        )


def _terminal_result(
    start: Mapping[str, Any], terminal_paths: tuple[Path, ...]
) -> tuple[str | None, Path | None, str | None]:
    present = [path for path in terminal_paths if path.is_file()]
    if not present:
        return None, None, None
    if len(present) != 1:
        return None, None, "TERMINAL_EVIDENCE_CONFLICT"
    path = present[0]
    expected = {
        "completed.json": ("completed", "COMPLETED"),
        "failed.json": ("failed", "FAILED"),
    }.get(path.name)
    if expected is None:
        return None, None, "TERMINAL_EVIDENCE_INVALID"
    try:
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
        result = DeliveryResult.from_dict(raw)
    except (OSError, json.JSONDecodeError, ContractError, TypeError, ValueError):
        return None, None, "TERMINAL_EVIDENCE_INVALID"
    if (
        result.message_id != start["message_id"]
        or result.run_id != start["run_id"]
        or result.adapter != start["adapter"]
        or result.status != expected[0]
    ):
        return None, None, "TERMINAL_EVIDENCE_IDENTITY_MISMATCH"
    return expected[1], path, None


def inspect_native_activity(
    started_path: Path,
    *,
    terminal_paths: tuple[Path, ...] = (),
    process_probe: Callable[[int, str], Mapping[str, Any]] = process_probe,
    native_probe: Callable[[Mapping[str, Any]], Mapping[str, Any]] | None = None,
    observed_at: str | None = None,
    max_activity_age_seconds: int = 300,
) -> dict[str, Any]:
    start = validate_native_start(started_path)
    observed = observed_at or utc_now()
    terminal_status, terminal, terminal_error = _terminal_result(start, terminal_paths)
    if terminal_error is not None:
        return {
            "schema_version": ACTIVITY_SCHEMA,
            "status": "UNKNOWN",
            "observed_at": observed,
            "process": None,
            "native_task": start["native_task"],
            "last_event": None,
            "waiting_on": None,
            "terminal_evidence": None,
            "error": terminal_error,
        }
    if terminal is not None and terminal_status is not None:
        return {
            "schema_version": ACTIVITY_SCHEMA,
            "status": terminal_status,
            "observed_at": observed,
            "process": None,
            "native_task": start["native_task"],
            "last_event": None,
            "waiting_on": None,
            "terminal_evidence": str(terminal),
            "error": None,
        }

    current_started_path = started_path
    current_start = start
    if native_probe is None:
        try:
            current_started_path, current_start = _current_native_start(started_path, start)
        except NativeActivityError:
            return {
                "schema_version": ACTIVITY_SCHEMA,
                "status": "UNKNOWN",
                "observed_at": observed,
                "process": {"exists": None, "identity_matches": None},
                "native_task": start["native_task"],
                "last_event": None,
                "waiting_on": None,
                "terminal_evidence": None,
                "error": "NATIVE_ACTIVITY_IDENTITY_MISMATCH",
            }
        native_probe = lambda value: _file_native_probe(current_started_path, value)

    # A Desktop bridge CLI only attests the platform injection.  It is not the
    # executor of the already-running Desktop turn, so platform activity is the
    # authoritative liveness source for this backend.
    if current_start["native_task"]["kind"] in PLATFORM_ACTIVITY_TASK_KINDS:
        native, mapped, error, projection_observed = _inspect_native_projection(
            current_start, native_probe, observed_at, max_activity_age_seconds
        )
        return {
            "schema_version": ACTIVITY_SCHEMA,
            "status": mapped,
            "observed_at": projection_observed,
            "process": None,
            "native_task": current_start["native_task"],
            "last_event": native.get("last_event"),
            "waiting_on": native.get("waiting_on"),
            "terminal_evidence": None,
            "error": error,
        }

    try:
        process = dict(
            process_probe(
                int(current_start["process"]["pid"]),
                str(current_start["process"]["creation_time"]),
            )
        )
    except (NativeActivityError, OSError):
        return {
            "schema_version": ACTIVITY_SCHEMA,
            "status": "UNKNOWN",
            "observed_at": observed,
            "process": {"exists": None, "identity_matches": None},
            "native_task": current_start["native_task"],
            "last_event": None,
            "waiting_on": None,
            "terminal_evidence": None,
            "error": "PROCESS_PROBE_FAILED",
        }
    if set(process) != {"exists", "identity_matches"} or not all(
        isinstance(process[name], bool) for name in process
    ):
        raise NativeActivityError("process probe returned an invalid result")
    if not process["exists"] or not process["identity_matches"]:
        return {
            "schema_version": ACTIVITY_SCHEMA,
            "status": "DEAD_WITHOUT_TERMINAL",
            "observed_at": observed,
            "process": process,
            "native_task": current_start["native_task"],
            "last_event": None,
            "waiting_on": None,
            "terminal_evidence": None,
            "error": None,
        }
    native, mapped, error, projection_observed = _inspect_native_projection(
        current_start, native_probe, observed_at, max_activity_age_seconds
    )
    return {
        "schema_version": ACTIVITY_SCHEMA,
        "status": mapped,
        "observed_at": projection_observed,
        "process": process,
        "native_task": current_start["native_task"],
        "last_event": native.get("last_event"),
        "waiting_on": native.get("waiting_on"),
        "terminal_evidence": None,
        "error": error,
    }
