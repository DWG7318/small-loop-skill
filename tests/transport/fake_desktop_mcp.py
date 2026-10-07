"""Native boundary fixture only; production parsing/identity checks remain real."""
import json
from xml.sax.saxutils import escape
import os
import sys
from pathlib import Path

mode = os.environ.get("FAKE_DESKTOP_MODE", "normal")
sent = None

def emit(request, result):
    print(json.dumps({"jsonrpc": "2.0", "id": request["id"], "result": result}), flush=True)

for line in sys.stdin:
    request = json.loads(line)
    if request.get("jsonrpc") != "2.0":
        raise RuntimeError("MCP framing must include jsonrpc")
    method = request["method"]
    if method == "initialize":
        emit(request, {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}}, "serverInfo": {"name": "fixture", "version": "1"}})
    elif method == "notifications/initialized":
        continue
    elif method == "tools/list":
        emit(request, {"tools": [{"name": n, "inputSchema": {"type": "object"}} for n in ("read_thread", "send_message_to_thread")]})
    elif method == "tools/call":
        p = request["params"]
        calls_path = Path.cwd() / "native-calls.jsonl"
        previous_calls = calls_path.read_text(encoding="utf-8").splitlines() if calls_path.is_file() else []
        with calls_path.open("a", encoding="utf-8") as output:
            output.write(json.dumps(p) + "\n")
        if p["name"] == "send_message_to_thread":
            sent = p
            value = {"threadId": "thr_exact"}
        elif p["name"] == "read_thread":
            effective_mode = mode.removeprefix("late-") if mode.startswith("late-") else mode
            effective_sent = sent
            if effective_sent is None and mode.startswith("late-"):
                for raw in reversed(previous_calls):
                    candidate = json.loads(raw)
                    if candidate.get("name") == "send_message_to_thread":
                        effective_sent = candidate
                        break
            items = []
            if effective_sent and effective_mode != "unconfirmed":
                prompt = effective_sent["arguments"]["prompt"]
                caller = (
                    "wrong-caller"
                    if effective_mode == "wrong-caller"
                    else effective_sent.get("_meta", {}).get("codex_thread_id")
                )
                if effective_mode == "wrong-payload":
                    prompt += "changed"
                text = f"<codex_delegation>\n  <source_thread_id>{escape(caller)}</source_thread_id>\n  <input>{escape(prompt)}</input>\n</codex_delegation>"
                items = [{"id": "item-exact", "type": "functionCallOutput", "name": "send_message_to_thread", "namespace": "codex_app", "output": {"text": text, "truncated": effective_mode == "truncated"}}]
                if effective_mode == "duplicate":
                    items.append({**items[0], "id": "item-other"})
            value = {"schemaVersion": 1, "thread": {"id": "thr_wrong" if mode == "wrong-thread" else "thr_exact", "hostId": "remote" if mode == "wrong-host" else "local", "cwd": str(Path.cwd()), "status": {"type": "active" if mode == "active" else "idle"}},
                     "page": {"hasMore": False}, "turns": [{"id": "turn-new" if effective_sent else "turn-old", "status": "completed", "items": items}]}
            if mode in {"active", "active-running", "old-item", "ambiguous-active"}:
                value["thread"]["status"]["type"] = "active"
                value["turns"][0]["id"] = "turn-old"
                value["turns"][0]["status"] = "completed" if sent and mode != "active-running" else "inProgress"
                if mode == "old-item" and not sent:
                    value["turns"][0]["items"] = [{"id": "item-exact", "type": "userMessage"}]
                if mode == "ambiguous-active" and not sent:
                    value["turns"].append({"id": "other-active", "status": "inProgress", "items": []})
            if mode == "malformed-status":
                value["thread"]["status"] = None
            if sent and mode == "malformed-item":
                value["turns"][0]["items"] = [None]
            if sent and mode == "malformed-items":
                value["turns"][0]["items"] = None
            if sent and mode == "failed-turn":
                value["turns"][0]["status"] = "failed"
        else:
            raise RuntimeError("unexpected tool")
        emit(request, {"content": [{"type": "text", "text": json.dumps(value)}], "isError": False})
    else:
        raise RuntimeError("unexpected RPC method")
