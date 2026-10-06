from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Mapping

from slk_transport.native_activity import make_native_start


def write_late_desktop_start(
    attempt: Path, endpoint: Mapping[str, object], envelope: Mapping[str, object],
) -> bytes:
    attempt.mkdir(parents=True, exist_ok=True)
    prompt = "exact late Desktop delivery"
    prompt_sha256 = hashlib.sha256(prompt.encode()).hexdigest()
    address = endpoint["address"]
    assert isinstance(address, Mapping)
    binding = address["desktop"]
    assert isinstance(binding, Mapping)
    target = str(address["thread_id"])
    caller = str(binding["caller_thread_id"])
    message_id = str(envelope["message_id"])
    turn_id = "turn-late"
    item_id = "item-late"

    values = {
        "endpoint.json": dict(endpoint),
        "envelope.json": dict(envelope),
        "desktop-prompt.json": {"message_id": message_id, "prompt": prompt},
        "desktop-readback-anchor.json": {
            "schema_version": "slk.desktop-readback-anchor/v1",
            "thread_id": target,
            "host_id": endpoint["host_id"],
            "caller_thread_id": caller,
            "message_id": message_id,
            "prompt_sha256": prompt_sha256,
            "previous_turn_ids": [],
            "previous_item_ids": [],
            "active_turn_ids": [turn_id],
        },
        "desktop-send.json": {
            "thread_id": target,
            "caller_thread_id": caller,
            "message_id": message_id,
            "prompt_sha256": prompt_sha256,
            "requested_model": binding["model"],
            "requested_effort": binding["reasoning_effort"],
            "result": {"threadId": target},
        },
        "desktop-readback.json": {
            "thread_id": target,
            "turn_id": turn_id,
            "turn_status": "inProgress",
            "platform_item_id": item_id,
            "caller_thread_id": caller,
            "message_id": message_id,
            "platform_item": {"id": item_id, "type": "functionCallOutput"},
        },
        "started.json": make_native_start(
            adapter=str(endpoint["adapter"]),
            run_id=str(envelope["run_id"]),
            cell_id=str(envelope["cell_id"]),
            message_id=message_id,
            request_sha256=str(envelope["payload_sha256"]),
            native_request_sha256=prompt_sha256,
            native_task_kind="codex-desktop-turn",
            native_task_id=f"{target}:{turn_id}:{item_id}",
            native_task_status="RUNNING",
            pid=os.getpid(),
        ),
        "failed.json": {
            "schema_version": "slk.transport-result/v1",
            "message_id": message_id,
            "run_id": envelope["run_id"],
            "adapter": endpoint["adapter"],
            "status": "failed",
            "native_identity": {},
            "error_code": "CODEX_DESKTOP_READBACK_UNPROVED",
            "evidence": [
                "accepted.json", "desktop-prompt.json", "desktop-readback-anchor.json",
                "desktop-send.json", "endpoint.json", "envelope.json",
            ],
        },
    }
    for name, value in values.items():
        (attempt / name).write_text(
            json.dumps(value, ensure_ascii=False, sort_keys=True), encoding="utf-8"
        )
    return (attempt / "failed.json").read_bytes()


def desktop_endpoint(endpoint: dict[str, object], tmp_path: Path) -> None:
    runtime = tmp_path / "codex-runtime.exe"
    plugin = tmp_path / "codex-plugin.js"
    runtime.write_bytes(b"runtime")
    plugin.write_bytes(b"plugin")
    endpoint["address"] = {
        "command": [str(runtime.resolve()), str(plugin.resolve())],
        "thread_id": "thread-supervisor",
        "cwd": str(tmp_path.resolve()),
        "startup_timeout_seconds": 1,
        "turn_timeout_seconds": 1,
        "desktop": {
            "caller_thread_id": "thread-checker",
            "model": "gpt-6.1-sol",
            "reasoning_effort": "xhigh",
            "plugin_sha256": hashlib.sha256(plugin.read_bytes()).hexdigest(),
        },
    }
