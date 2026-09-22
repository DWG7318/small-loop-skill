"""Closed immutable task-file transport for native SLK workers."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict
from pathlib import Path
from typing import Any, Mapping

from .contracts import Endpoint, Envelope
from .evidence import Attempt, EvidenceError


TASK_SCHEMA = "slk.transport-task/v1"
TASK_FIELDS = frozenset(
    {
        "schema_version", "message_id", "run_id", "go_id", "cell_id",
        "endpoint", "envelope", "result_contract", "result_path",
    }
)


class TaskFileError(RuntimeError):
    """Raised when a task file is not the immutable closed object expected."""


def canonical_task_bytes(value: Mapping[str, Any]) -> bytes:
    if not isinstance(value, Mapping) or set(value) != TASK_FIELDS:
        raise TaskFileError("transport task must use the exact field set")
    try:
        return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise TaskFileError("transport task is not canonical JSON") from exc


def create_task_file(
    attempt: Attempt,
    destination: Path,
    endpoint: Endpoint,
    envelope: Envelope,
    result_contract: Mapping[str, Any],
    result_path: Path,
) -> tuple[Path, str]:
    value = {
        "schema_version": TASK_SCHEMA,
        "message_id": envelope.message_id,
        "run_id": envelope.run_id,
        "go_id": envelope.go_id,
        "cell_id": envelope.cell_id,
        "endpoint": asdict(endpoint),
        "envelope": asdict(envelope),
        "result_contract": dict(result_contract),
        "result_path": str(result_path.resolve()),
    }
    data = canonical_task_bytes(value)
    digest = hashlib.sha256(data).hexdigest()
    try:
        descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        attempt.write_text_once("transport-task.json", data.decode("utf-8"))
    except (OSError, EvidenceError) as exc:
        destination.unlink(missing_ok=True)
        raise TaskFileError("transport task could not be written exactly once") from exc
    return destination, digest


def verify_task_file(path: Path, expected_sha256: str) -> Mapping[str, Any]:
    if not path.is_absolute() or not path.is_file():
        raise TaskFileError("transport task path must be an existing absolute file")
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != expected_sha256:
        raise TaskFileError("transport task hash mismatch")
    try:
        value = json.loads(data.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TaskFileError("transport task is not valid JSON") from exc
    if not isinstance(value, dict) or set(value) != TASK_FIELDS:
        raise TaskFileError("transport task must use the exact field set")
    if value.get("schema_version") != TASK_SCHEMA:
        raise TaskFileError("transport task schema mismatch")
    if canonical_task_bytes(value) != data:
        raise TaskFileError("transport task bytes are not canonical")
    return value
