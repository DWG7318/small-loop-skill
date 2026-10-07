"""Trusted, read-only attestation for an already-running Codex Desktop OW turn."""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
from pathlib import Path
from typing import Any, Mapping
from uuid import UUID

from .adapters.base import AdapterError
from .adapters.codex_desktop import DesktopClient
from .native_activity import (
    TASK_ACTIVITY_SCHEMA,
    _atomic_json,
    make_native_start,
    sha256_file,
    utc_now,
    validate_native_start,
)


REQUEST_SCHEMA = "slk.desktop-overwatcher-attestation-request/v1"
ATTESTATION_SCHEMA = "slk.desktop-overwatcher-attestation/v1"
REQUEST_FIELDS = frozenset({
    "schema_version", "method_version", "attestation_id", "run_id",
    "role_instance_id", "endpoint_ref", "thread_id", "host_id", "cwd",
    "turn_id", "platform_input_item_id", "reader_thread_id", "command",
    "plugin_sha256", "timeout_seconds",
})
ATTESTATION_FIELDS = frozenset({
    "schema_version", "method_version", "attestation_id", "run_id",
    "role_instance_id", "endpoint_ref", "thread_id", "host_id", "cwd",
    "turn_id", "platform_input_item_id", "platform_input_sha256",
    "request_sha256", "plugin_sha256", "observed_at", "thread_status",
    "turn_status", "native_task_id", "started_sha256",
})
SHA256 = re.compile(r"^[0-9a-f]{64}$")


class OverwatcherDesktopError(ValueError):
    """The frozen Desktop OW identity or its current platform state is unproved."""


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise OverwatcherDesktopError(f"{label} must be one canonical non-empty string")
    return value


def _read_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise OverwatcherDesktopError(f"{label} is unreadable") from exc
    if not isinstance(value, dict):
        raise OverwatcherDesktopError(f"{label} must be an object")
    return value


def _request(path: Path, expected_sha256: str) -> dict[str, Any]:
    if not SHA256.fullmatch(expected_sha256) or sha256_file(path) != expected_sha256:
        raise OverwatcherDesktopError("Desktop OW request hash does not match")
    value = _read_object(path, "Desktop OW request")
    if set(value) != REQUEST_FIELDS or value.get("schema_version") != REQUEST_SCHEMA:
        raise OverwatcherDesktopError("Desktop OW request is not closed")
    if value.get("method_version") != "4.4.2":
        raise OverwatcherDesktopError("Desktop OW request method version is unsupported")
    try:
        UUID(_text(value.get("attestation_id"), "attestation_id"))
    except ValueError as exc:
        raise OverwatcherDesktopError("attestation_id must be one UUID") from exc
    for field in (
        "run_id", "role_instance_id", "endpoint_ref", "thread_id", "host_id",
        "turn_id", "platform_input_item_id", "reader_thread_id",
    ):
        _text(value.get(field), field)
    cwd = Path(_text(value.get("cwd"), "cwd"))
    if not cwd.is_absolute() or not cwd.is_dir():
        raise OverwatcherDesktopError("Desktop OW cwd must be an existing absolute directory")
    command = value.get("command")
    if (
        not isinstance(command, list)
        or len(command) != 2
        or not all(isinstance(item, str) and Path(item).is_absolute() and Path(item).is_file() for item in command)
    ):
        raise OverwatcherDesktopError("Desktop OW command must contain the installed runtime and plugin")
    plugin_sha256 = value.get("plugin_sha256")
    if not isinstance(plugin_sha256, str) or not SHA256.fullmatch(plugin_sha256):
        raise OverwatcherDesktopError("Desktop OW plugin hash is invalid")
    if sha256_file(Path(command[1])) != plugin_sha256:
        raise OverwatcherDesktopError("Desktop OW plugin changed after preparation")
    timeout = value.get("timeout_seconds")
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not 0 < timeout <= 60:
        raise OverwatcherDesktopError("Desktop OW timeout must be within sixty seconds")
    return value


def _assert_host(request: Mapping[str, Any], *, frozen_reader: bool) -> str:
    try:
        reader_thread_id = _text(os.environ.get("CODEX_THREAD_ID"), "current reader thread")
    except OverwatcherDesktopError as exc:
        raise OverwatcherDesktopError("trusted Desktop reader capability was not inherited") from exc
    if (not os.environ.get("CODEX_APP_TOOLS_PIPE_PATH")
        or os.environ.get("CODEX_INTERNAL_ORIGINATOR_OVERRIDE") != "Codex Desktop"
        or (frozen_reader and reader_thread_id != request["reader_thread_id"])):
        raise OverwatcherDesktopError("trusted Desktop reader capability was not inherited")
    return reader_thread_id


def _platform_snapshot(request: Mapping[str, Any], *, frozen_reader: bool) -> dict[str, Any]:
    reader_thread_id = _assert_host(request, frozen_reader=frozen_reader)
    client = DesktopClient(list(request["command"]), Path(str(request["cwd"])))
    timeout = float(request["timeout_seconds"])
    try:
        client.request(1, "initialize", {
            "protocolVersion": "2024-11-05", "capabilities": {},
            "clientInfo": {"name": "slk_overwatcher_desktop_status", "version": "4.4.2"},
        }, timeout)
        client.notify("notifications/initialized", {})
        catalog = client.request(2, "tools/list", {}, timeout)
        names = {tool.get("name") for tool in catalog.get("tools", []) if isinstance(tool, Mapping)}
        if "read_thread" not in names:
            raise OverwatcherDesktopError("installed Desktop plugin lacks read_thread")
        view = client.call(3, "read_thread", {
            "threadId": request["thread_id"], "hostId": request["host_id"],
            "turnLimit": 1, "includeOutputs": True, "maxOutputCharsPerItem": 4096,
        }, reader_thread_id, timeout)
    except TimeoutError as exc:
        raise OverwatcherDesktopError("Desktop OW read_thread timed out") from exc
    finally:
        client.close()

    thread = view.get("thread")
    turns = view.get("turns")
    if (
        not isinstance(thread, Mapping)
        or thread.get("id") != request["thread_id"]
        or thread.get("hostId") != request["host_id"]
        or not isinstance(thread.get("cwd"), str)
        or Path(str(thread["cwd"])).resolve() != Path(str(request["cwd"])).resolve()
        or not isinstance(thread.get("status"), Mapping)
        or not isinstance(turns, list)
    ):
        raise OverwatcherDesktopError("Desktop OW thread identity does not match the frozen binding")
    matching_turns = [turn for turn in turns if isinstance(turn, Mapping) and turn.get("id") == request["turn_id"]]
    if len(matching_turns) != 1:
        raise OverwatcherDesktopError("Desktop OW turn identity is absent or ambiguous")
    turn = matching_turns[0]
    items = turn.get("items")
    if not isinstance(items, list):
        raise OverwatcherDesktopError("Desktop OW turn items are unavailable")
    matching_items = [item for item in items if isinstance(item, Mapping) and item.get("id") == request["platform_input_item_id"]]
    if len(matching_items) != 1:
        raise OverwatcherDesktopError("Desktop OW input item identity is absent or ambiguous")
    item = matching_items[0]
    output = item.get("output")
    if (
        item.get("type") != "functionCallOutput"
        or item.get("name") != "send_message_to_thread"
        or item.get("namespace") != "codex_app"
        or not isinstance(output, Mapping)
        or output.get("truncated") is not False
        or not isinstance(output.get("text"), str)
        or not output["text"]
    ):
        raise OverwatcherDesktopError("Desktop OW platform input is not an exact accepted delivery")
    thread_status = thread["status"].get("type")
    turn_status = turn.get("status")
    if thread_status not in {"active", "idle"} or turn_status not in {
        "active", "inProgress", "completed", "failed", "interrupted", "cancelled",
    }:
        raise OverwatcherDesktopError("Desktop OW platform status is unsupported")
    if turn_status in {"active", "inProgress"} and thread_status != "active":
        raise OverwatcherDesktopError("Desktop OW thread and turn status are inconsistent")
    updated = thread.get("updatedAt")
    sequence = updated if isinstance(updated, int) and not isinstance(updated, bool) and updated >= 0 else int(time.time() * 1000)
    return {
        "thread_status": thread_status,
        "turn_status": turn_status,
        "platform_input_sha256": hashlib.sha256(output["text"].encode("utf-8")).hexdigest(),
        "sequence": sequence,
    }


def _write_once(path: Path, value: Mapping[str, Any]) -> None:
    if path.exists():
        if _read_object(path, path.name) != dict(value):
            raise OverwatcherDesktopError(f"{path.name} conflicts with existing evidence")
        return
    _atomic_json(path, value)


def _copy_request_once(source: Path, destination: Path) -> None:
    data = source.read_bytes()
    if destination.exists():
        if destination.read_bytes() != data:
            raise OverwatcherDesktopError("Desktop OW request conflicts with existing evidence")
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        with destination.open("xb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError:
        if destination.read_bytes() != data:
            raise OverwatcherDesktopError("Desktop OW request conflicts with existing evidence")


def attest_desktop_overwatcher(
    request_path: Path,
    *,
    request_sha256: str,
    evidence_root: Path,
) -> dict[str, Any]:
    """Attest one existing active OW turn without sending, resuming or creating work."""

    request_path = request_path.resolve()
    root = evidence_root.resolve()
    if not root.is_absolute():
        raise OverwatcherDesktopError("Desktop OW evidence root must be absolute")
    request = _request(request_path, request_sha256)
    copied_request = root / "desktop-overwatcher-request.json"
    started_path = root / "started.json"
    attestation_path = root / "desktop-overwatcher-attestation.json"
    _copy_request_once(request_path, copied_request)
    if attestation_path.is_file():
        attestation = validate_desktop_overwatcher_attestation(
            attestation_path,
            attestation_sha256=sha256_file(attestation_path),
            run_id=str(request["run_id"]),
            role_instance_id=str(request["role_instance_id"]),
            endpoint_ref=str(request["endpoint_ref"]),
            started_path=started_path,
        )
        started = validate_native_start(
            started_path, adapter="codex-overwatcher", run_id=str(request["run_id"]),
            cell_id="RUN-OVERWATCH", message_id=str(request["attestation_id"]),
            request_sha256=request_sha256,
            native_request_sha256=str(attestation["platform_input_sha256"]),
        )
        if started["native_task"] != {
            "kind": "codex-desktop-turn", "id": attestation["native_task_id"], "status": "RUNNING",
        }:
            raise OverwatcherDesktopError("existing Desktop OW start changed native identity")
        return {
            "status": "ATTESTED", "run_id": request["run_id"],
            "role_instance_id": request["role_instance_id"], "endpoint_ref": request["endpoint_ref"],
            "started_path": str(started_path), "started_sha256": sha256_file(started_path),
            "attestation_path": str(attestation_path), "attestation_sha256": sha256_file(attestation_path),
        }
    snapshot = _platform_snapshot(request, frozen_reader=True)
    if snapshot["thread_status"] != "active" or snapshot["turn_status"] not in {"active", "inProgress"}:
        raise OverwatcherDesktopError("Desktop OW turn is not positively active")
    native_task_id = f"{request['thread_id']}:{request['turn_id']}:{request['platform_input_item_id']}"
    if started_path.is_file():
        started = validate_native_start(
            started_path, adapter="codex-overwatcher", run_id=str(request["run_id"]),
            cell_id="RUN-OVERWATCH", message_id=str(request["attestation_id"]),
            request_sha256=request_sha256,
            native_request_sha256=str(snapshot["platform_input_sha256"]),
        )
        if started["native_task"] != {
            "kind": "codex-desktop-turn", "id": native_task_id, "status": "RUNNING",
        }:
            raise OverwatcherDesktopError("existing Desktop OW start changed native identity")
    else:
        started = make_native_start(
            adapter="codex-overwatcher", run_id=str(request["run_id"]), cell_id="RUN-OVERWATCH",
            message_id=str(request["attestation_id"]), request_sha256=request_sha256,
            native_request_sha256=str(snapshot["platform_input_sha256"]),
            native_task_kind="codex-desktop-turn", native_task_id=native_task_id,
            native_task_status="RUNNING", pid=os.getpid(),
        )
        _write_once(started_path, started)
    attestation = {
        "schema_version": ATTESTATION_SCHEMA, "method_version": "4.4.2",
        "attestation_id": request["attestation_id"], "run_id": request["run_id"],
        "role_instance_id": request["role_instance_id"], "endpoint_ref": request["endpoint_ref"],
        "thread_id": request["thread_id"], "host_id": request["host_id"], "cwd": request["cwd"],
        "turn_id": request["turn_id"], "platform_input_item_id": request["platform_input_item_id"],
        "platform_input_sha256": snapshot["platform_input_sha256"], "request_sha256": request_sha256,
        "plugin_sha256": request["plugin_sha256"], "observed_at": started["observed_at"],
        "thread_status": snapshot["thread_status"], "turn_status": snapshot["turn_status"],
        "native_task_id": native_task_id, "started_sha256": sha256_file(started_path),
    }
    _write_once(attestation_path, attestation)
    activity = _activity(request, attestation, snapshot)
    _atomic_json(root / "native-activity.json", activity)
    return {
        "status": "ATTESTED", "run_id": request["run_id"],
        "role_instance_id": request["role_instance_id"], "endpoint_ref": request["endpoint_ref"],
        "started_path": str(started_path), "started_sha256": sha256_file(started_path),
        "attestation_path": str(attestation_path), "attestation_sha256": sha256_file(attestation_path),
    }


def validate_desktop_overwatcher_attestation(
    path: Path,
    *,
    attestation_sha256: str,
    run_id: str | None = None,
    role_instance_id: str | None = None,
    endpoint_ref: str | None = None,
    started_path: Path | None = None,
) -> dict[str, Any]:
    if not SHA256.fullmatch(attestation_sha256) or sha256_file(path) != attestation_sha256:
        raise OverwatcherDesktopError("Overwatcher attestation hash does not match")
    value = _read_object(path, "Overwatcher Desktop attestation")
    if set(value) != ATTESTATION_FIELDS or value.get("schema_version") != ATTESTATION_SCHEMA:
        raise OverwatcherDesktopError("Overwatcher Desktop attestation is not closed")
    if value.get("method_version") != "4.4.2":
        raise OverwatcherDesktopError("Overwatcher Desktop attestation version is unsupported")
    for field in ATTESTATION_FIELDS - {"schema_version", "method_version"}:
        if not isinstance(value.get(field), str) or not value[field]:
            raise OverwatcherDesktopError(f"Overwatcher Desktop attestation {field} is invalid")
    for field in ("platform_input_sha256", "request_sha256", "plugin_sha256", "started_sha256"):
        if not SHA256.fullmatch(value[field]):
            raise OverwatcherDesktopError(f"Overwatcher Desktop attestation {field} is invalid")
    expected = {"run_id": run_id, "role_instance_id": role_instance_id, "endpoint_ref": endpoint_ref}
    if any(wanted is not None and value[field] != wanted for field, wanted in expected.items()):
        raise OverwatcherDesktopError("Overwatcher attestation does not match the frozen binding")
    if started_path is not None and sha256_file(started_path) != value["started_sha256"]:
        raise OverwatcherDesktopError("Overwatcher attestation does not match native start evidence")
    return value


def _activity(
    request: Mapping[str, Any],
    attestation: Mapping[str, Any],
    snapshot: Mapping[str, Any],
) -> dict[str, Any]:
    status = {
        "active": "RUNNING", "inProgress": "RUNNING", "completed": "COMPLETED",
        "failed": "FAILED", "interrupted": "FAILED", "cancelled": "FAILED",
    }[str(snapshot["turn_status"])]
    detail = json.dumps({
        "thread_id": request["thread_id"], "turn_id": request["turn_id"],
        "thread_status": snapshot["thread_status"], "turn_status": snapshot["turn_status"],
        "platform_input_sha256": snapshot["platform_input_sha256"],
    }, sort_keys=True, separators=(",", ":")).encode("utf-8")
    sequence = int(snapshot["sequence"])
    return {
        "schema_version": TASK_ACTIVITY_SCHEMA, "adapter": "codex-overwatcher",
        "run_id": request["run_id"], "cell_id": "RUN-OVERWATCH",
        "message_id": request["attestation_id"], "native_task_id": attestation["native_task_id"],
        "status": status, "sequence": sequence, "observed_at": utc_now(),
        "last_event": {"kind": "CODEX_DESKTOP_TURN_READBACK", "sequence": sequence,
                       "detail_sha256": hashlib.sha256(detail).hexdigest()},
        "waiting_on": "CODEX_DESKTOP_TURN" if status == "RUNNING" else None,
    }


def desktop_overwatcher_probe(
    attestation_path: Path,
    *,
    attestation_sha256: str,
    started_path: Path,
    start: Mapping[str, Any],
) -> Mapping[str, Any]:
    """Query the exact frozen OW turn now; never accept the saved activity snapshot as liveness."""

    try:
        attestation_path = attestation_path.resolve()
        request_path = attestation_path.with_name("desktop-overwatcher-request.json")
        attestation = validate_desktop_overwatcher_attestation(
            attestation_path, attestation_sha256=attestation_sha256,
            started_path=started_path,
        )
        request = _request(request_path, str(attestation["request_sha256"]))
        expected = {
            "attestation_id": start.get("message_id"), "run_id": start.get("run_id"),
            "role_instance_id": attestation["role_instance_id"], "endpoint_ref": attestation["endpoint_ref"],
            "thread_id": attestation["thread_id"], "host_id": attestation["host_id"],
            "cwd": attestation["cwd"], "turn_id": attestation["turn_id"],
            "platform_input_item_id": attestation["platform_input_item_id"],
            "plugin_sha256": attestation["plugin_sha256"],
        }
        if any(request.get(field) != wanted for field, wanted in expected.items()):
            raise OverwatcherDesktopError("Overwatcher request, attestation and native start identity drifted")
        if (
            start.get("adapter") != "codex-overwatcher"
            or start.get("cell_id") != "RUN-OVERWATCH"
            or start.get("request_sha256") != attestation["request_sha256"]
            or start.get("native_request_sha256") != attestation["platform_input_sha256"]
            or start.get("native_task", {}).get("kind") != "codex-desktop-turn"
            or start.get("native_task", {}).get("id") != attestation["native_task_id"]
        ):
            raise OverwatcherDesktopError("Overwatcher native start does not match the attested turn")
        snapshot = _platform_snapshot(request, frozen_reader=False)
        if snapshot["platform_input_sha256"] != attestation["platform_input_sha256"]:
            raise OverwatcherDesktopError("Overwatcher platform input changed after attestation")
        return _activity(request, attestation, snapshot)
    except (AdapterError, OSError, ValueError, TypeError, KeyError):
        return {"status": "UNKNOWN", "error": "NATIVE_QUERY_FAILED"}
