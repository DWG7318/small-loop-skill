"""Read-only Codex Desktop fixture for an already-running Overwatcher turn."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path


MODE = os.environ.get("FAKE_OW_DESKTOP_MODE", "active")
INPUT_TEXT = "<codex_delegation><input>observe the exact run</input></codex_delegation>"


def emit(request, result):
    print(json.dumps({"jsonrpc": "2.0", "id": request["id"], "result": result}), flush=True)


for line in sys.stdin:
    request = json.loads(line)
    method = request["method"]
    if method == "initialize":
        emit(request, {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "fixture", "version": "1"},
        })
    elif method == "notifications/initialized":
        continue
    elif method == "tools/list":
        tools = [] if MODE == "no-read" else [
            {"name": "read_thread", "inputSchema": {"type": "object"}},
        ]
        emit(request, {"tools": tools})
    elif method == "tools/call":
        params = request["params"]
        with (Path.cwd() / "ow-native-calls.jsonl").open("a", encoding="utf-8") as output:
            output.write(json.dumps(params) + "\n")
        if params["name"] != "read_thread":
            raise RuntimeError("Overwatcher status adapter must remain read-only")
        if MODE == "tool-error":
            emit(request, {"content": [], "isError": True})
            continue
        turn_status = "completed" if MODE == "completed" else "inProgress"
        thread_status = "idle" if MODE in {"completed", "idle-running"} else "active"
        item_id = "wrong-item" if MODE == "wrong-item" else "item-ow-input"
        value = {
            "schemaVersion": 1,
            "thread": {
                "id": "wrong-thread" if MODE == "wrong-thread" else "thread-ow",
                "hostId": "local",
                "cwd": str(Path.cwd()),
                "status": {"type": thread_status},
                "updatedAt": 1791251486,
            },
            "page": {"hasMore": False},
            "turns": [{
                "id": "turn-ow",
                "status": turn_status,
                "items": [{
                    "id": item_id,
                    "type": "functionCallOutput",
                    "name": "send_message_to_thread",
                    "namespace": "codex_app",
                    "output": {"text": INPUT_TEXT, "truncated": False},
                }],
            }],
        }
        emit(request, {"content": [{"type": "text", "text": json.dumps(value)}], "isError": False})
    else:
        raise RuntimeError("unexpected RPC method")
