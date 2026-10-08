"""Read native Desktop records; never turn a caller's receipt into platform proof."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any
import json
import xml.etree.ElementTree as ET


def codex_home() -> Path:
    return Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))).resolve()


def read_codex_item(path: Path, thread_id: str, item_id: str) -> dict[str, Any]:
    path = path.resolve()
    if (not path.is_relative_to(codex_home() / "sessions")
        or not path.name.startswith("rollout-") or thread_id not in path.name):
        raise ValueError("platform proof is not a native Codex Session record")
    found = []
    tool_wrappers = []
    delivered_output = None
    with path.open(encoding="utf-8-sig") as stream:
        header = json.loads(stream.readline())
        if (header.get("type") != "session_meta" or header.get("payload", {}).get("id") != thread_id
            or header["payload"].get("originator") != "Codex Desktop"):
            raise ValueError("native Desktop Session identity changed")
        for line in stream:
            if item_id not in line:
                continue
            row = json.loads(line)
            payload = row.get("payload", {})
            if row.get("type") == "response_item" and payload.get("id") == item_id:
                if (payload.get("type") != "function_call_output"
                    or payload.get("name") != "send_message_to_thread"
                    or payload.get("namespace") != "codex_app"):
                    raise ValueError("native item is not a platform-delivered message")
                root = ET.fromstring(payload["output"])
                if root.tag != "codex_delegation" or [child.tag for child in root] != ["source_thread_id", "input"]:
                    raise ValueError("native message delegation is not closed")
                delivered_output = payload['output']
                found.append({"kind": "delegation", "source_thread_id": root[0].text,
                    "text": root[1].text, "turn_id": payload.get(
                        "internal_chat_message_metadata_passthrough", {}).get("turn_id")})
            elif (row.get("type") == "event_msg" and payload.get("type") == "item_completed"
                  and payload.get("item", {}).get("id") == item_id
                  and payload["item"].get("type") == "UserMessage"):
                item = payload["item"]
                if (payload.get("thread_id") != thread_id or item.get("type") != "UserMessage"
                    or not item.get("content") or any(part.get("type") != "text" for part in item["content"])):
                    raise ValueError("Owner proof is not an actual platform UserMessage")
                found.append({"kind": "owner", "source_thread_id": thread_id,
                    "text": "".join(part["text"] for part in item["content"]), "turn_id": payload.get("turn_id")})
            elif (row.get('type') == 'event_msg' and payload.get('type') == 'item_completed'
                  and payload.get('item', {}).get('id') == item_id):
                if payload['item'].get('type') != 'FunctionCallOutput':
                    raise ValueError('native matching item has a conflicting type')
                tool_wrappers.append(payload)
    if len(found) != 1:
        raise ValueError("native platform item is missing or ambiguous")
    if any(found[0]['kind'] != 'delegation' or wrapper.get('thread_id') != thread_id
        or wrapper.get('turn_id') != found[0]['turn_id']
        or any(wrapper['item'].get(k) != v for k,v in {
            'name':'send_message_to_thread', 'namespace':'codex_app', 'output':delivered_output}.items())
        for wrapper in tool_wrappers):
        raise ValueError('native message representations contradict each other')
    return found[0]


def find_codex_item(thread_id: str, item_id: str) -> Path:
    matches = []
    for path in (codex_home() / "sessions").glob(f"*/*/*/rollout-*{thread_id}*.jsonl"):
        try:
            read_codex_item(path, thread_id, item_id)
        except ValueError as exc:
            if str(exc) == "native platform item is missing or ambiguous":
                continue
            raise
        matches.append(path.resolve())
    if len(matches) != 1:
        raise ValueError("exact native platform record is unavailable or duplicated")
    return matches[0]
