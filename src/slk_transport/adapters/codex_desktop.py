"""Codex adapter's opt-in native Desktop entry; no writer takeover or daemon."""
from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any, Mapping
from xml.sax.saxutils import escape

from .base import AdapterError
from ..contracts import DeliveryResult, Endpoint, Envelope, RESULT_SCHEMA, SHA256
from ..evidence import Attempt
from ..jsonrpc import JsonRpcProcess
from ..native_activity import TASK_ACTIVITY_SCHEMA, _atomic_json, make_native_start, utc_now


def validate_desktop_address(address: Mapping[str, Any]) -> None:
    binding = address["desktop"]
    if (not isinstance(binding, Mapping)
        or set(binding) != {"caller_thread_id", "model", "reasoning_effort", "plugin_sha256"}
        or any(not isinstance(binding[k], str) or not binding[k] or binding[k] != binding[k].strip() for k in binding)
        or binding["reasoning_effort"] not in {"high", "xhigh"}
        or not SHA256.fullmatch(binding["plugin_sha256"])):
        raise AdapterError("CODEX_ADDRESS_INVALID", "Desktop binding must be exact and versioned by plugin hash")
    command = address["command"]
    if len(command) != 2 or not all(Path(p).is_absolute() and Path(p).is_file() for p in command):
        raise AdapterError("CODEX_ADDRESS_INVALID", "Desktop command must name installed runtime and plugin files")
    if hashlib.sha256(Path(command[1]).read_bytes()).hexdigest() != binding["plugin_sha256"]:
        raise AdapterError("CODEX_DESKTOP_PLUGIN_CHANGED", "prepared Desktop plugin changed; repeat readiness")


class DesktopClient(JsonRpcProcess):
    def _receive(self, timeout: float) -> dict[str, Any]:
        value = super()._receive(timeout)
        # Desktop uses direct request results, not App Server notification history.
        del self.messages[:-1]
        return value

    def send(self, value: Mapping[str, Any]) -> None:
        super().send({"jsonrpc": "2.0", **value})

    def call(self, request_id: int, name: str, arguments: Mapping[str, Any], caller: str, timeout: float) -> Mapping[str, Any]:
        result = self.request(request_id, "tools/call", {"name": name, "arguments": dict(arguments),
            "_meta": {"codex_thread_id": caller}}, timeout)
        content = result.get("content")
        if (result.get("isError") is not False or not isinstance(content, list) or len(content) != 1
            or not isinstance(content[0], Mapping) or content[0].get("type") != "text"):
            raise AdapterError("CODEX_DESKTOP_TOOL_FAILED", f"Desktop {name} did not return one successful text result")
        try:
            value = json.loads(content[0]["text"])
        except (KeyError, ValueError, TypeError) as error:
            raise AdapterError("CODEX_DESKTOP_PROTOCOL_INVALID", "Desktop result is not readable JSON") from error
        if not isinstance(value, Mapping):
            raise AdapterError("CODEX_DESKTOP_PROTOCOL_INVALID", "Desktop result is not an object")
        return value


def _view(value: Mapping[str, Any], endpoint: Endpoint) -> tuple[Mapping[str, Any], list]:
    thread, turns = value.get("thread"), value.get("turns")
    if (not isinstance(thread, Mapping) or thread.get("id") != endpoint.address["thread_id"]
        or thread.get("hostId") != endpoint.host_id
        or not isinstance(thread.get("cwd"), str)
        or Path(thread["cwd"]).resolve() != Path(str(endpoint.address["cwd"])).resolve()):
        raise AdapterError("CODEX_THREAD_ID_MISMATCH", "Desktop readback differs from the prepared thread/host/workspace")
    if not isinstance(turns, list) or not all(isinstance(t, Mapping) and isinstance(t.get("id"), str) for t in turns):
        raise AdapterError("CODEX_DESKTOP_PROTOCOL_INVALID", "Desktop omitted native turn identities")
    if (not isinstance(thread.get("status"), Mapping)
        or any(not isinstance(t.get("items"), list)
               or not all(isinstance(i, Mapping) for i in t["items"]) for t in turns)):
        raise AdapterError("CODEX_DESKTOP_PROTOCOL_INVALID", "Desktop status or native items are malformed")
    return thread, turns


def deliver_desktop(endpoint: Endpoint, envelope: Envelope, attempt: Attempt, prompt: str,
                    *, wait_for_completion: bool = True) -> DeliveryResult:
    address, binding = endpoint.address, endpoint.address["desktop"]
    caller, target = binding["caller_thread_id"], address["thread_id"]
    if (os.environ.get("CODEX_THREAD_ID") != caller or not os.environ.get("CODEX_APP_TOOLS_PIPE_PATH")
        or os.environ.get("CODEX_INTERNAL_ORIGINATOR_OVERRIDE") != "Codex Desktop"):
        raise AdapterError("CODEX_DESKTOP_HOST_UNAVAILABLE", "the prepared Desktop executor capability was not inherited")
    if len(prompt) > 16000:
        raise AdapterError("CODEX_DESKTOP_PAYLOAD_TOO_LARGE", "delivery exceeds bounded native readback; use evidence references")
    expected = f"<codex_delegation>\n  <source_thread_id>{escape(caller)}</source_thread_id>\n  <input>{escape(prompt)}</input>\n</codex_delegation>"
    if len(expected) + 512 > 32768:
        raise AdapterError("CODEX_DESKTOP_PAYLOAD_TOO_LARGE", "escaped delivery exceeds bounded native readback")
    timeout = float(address["startup_timeout_seconds"])
    client = DesktopClient(list(address["command"]), Path(str(address["cwd"])))
    try:
        client.request(1, "initialize", {"protocolVersion": "2024-11-05", "capabilities": {},
            "clientInfo": {"name": "slk_transport_desktop", "version": "4.4.1"}}, timeout)
        client.notify("notifications/initialized", {})
        catalog = client.request(2, "tools/list", {}, timeout)
        if not {"read_thread", "send_message_to_thread"}.issubset({t.get("name") for t in catalog.get("tools", []) if isinstance(t, Mapping)}):
            raise AdapterError("CODEX_DESKTOP_HOST_UNAVAILABLE", "installed Desktop plugin lacks the required native tools")
        args = {"threadId": target, "hostId": endpoint.host_id, "turnLimit": 2,
                "includeOutputs": True, "maxOutputCharsPerItem": len(expected) + 512}
        before = client.call(3, "read_thread", args, caller, timeout)
        thread, turns = _view(before, endpoint)
        status = thread.get("status", {}).get("type")
        active = [t["id"] for t in turns if t.get("status") in {"inProgress", "active"}]
        if status not in {"idle", "active"}:
            raise AdapterError("CODEX_THREAD_TERMINAL", "Desktop did not positively confirm the target is available")
        if (status == "active" and len(active) != 1) or (status == "idle" and active):
            raise AdapterError("CODEX_ACTIVE_WRITER_UNRESOLVED", "Desktop active turn identity is ambiguous")
        previous = {t["id"] for t in turns}
        previous_items = {i.get("id") for t in turns for i in t["items"] if isinstance(i.get("id"), str)}
        sent = client.call(4, "send_message_to_thread", {"threadId": target, "hostId": endpoint.host_id,
            "model": binding["model"], "thinking": binding["reasoning_effort"], "prompt": prompt}, caller, timeout)
        attempt.write_json_once("desktop-send.json", {"thread_id": target, "caller_thread_id": caller,
            "message_id": envelope.message_id, "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
            "requested_model": binding["model"], "requested_effort": binding["reasoning_effort"], "result": dict(sent)})
        if sent.get("threadId") != target:
            raise AdapterError("CODEX_THREAD_ID_MISMATCH", "Desktop acknowledged a different target")
        deadline, request_id, proven = time.monotonic() + timeout, 5, None
        finish_deadline = time.monotonic() + float(address["turn_timeout_seconds"])
        while True:
            view = client.call(request_id, "read_thread", args, caller, timeout)
            request_id += 1
            _, turns = _view(view, endpoint)
            matches = []
            for turn in turns:
                for item in turn.get("items", []):
                    output = item.get("output", {}) if isinstance(item, Mapping) else {}
                    if ((turn["id"] not in previous or turn["id"] in active)
                        and isinstance(item.get("id"), str) and item["id"] not in previous_items
                        and item.get("type") == "functionCallOutput" and item.get("name") == "send_message_to_thread"
                        and item.get("namespace") == "codex_app" and isinstance(output, Mapping)
                        and output.get("truncated") is False and output.get("text") == expected):
                        matches.append((turn, item))
            if len(matches) > 1:
                raise AdapterError("CODEX_DESKTOP_READBACK_AMBIGUOUS", "multiple native items claim this exact delivery")
            if matches:
                turn, item = matches[0]
                if turn.get("status") not in {"completed", "inProgress", "active"}:
                    raise AdapterError("CODEX_TURN_FAILED", "Desktop native turn did not complete successfully")
                identity = (turn["id"], item["id"])
                if proven is not None and proven != identity:
                    raise AdapterError("CODEX_DESKTOP_READBACK_AMBIGUOUS", "delivery native identity changed")
                if proven is None:
                    proven = identity
                    proof = {"thread_id": target, "turn_id": turn["id"], "platform_item_id": item["id"],
                             "caller_thread_id": caller, "message_id": envelope.message_id, "platform_item": dict(item)}
                    attempt.write_json_once("desktop-readback.json", proof)
                    attempt.write_json_once("started.json", make_native_start(adapter=endpoint.adapter,
                        run_id=envelope.run_id, cell_id=envelope.cell_id, message_id=envelope.message_id,
                        request_sha256=envelope.payload_sha256, native_request_sha256=hashlib.sha256(prompt.encode()).hexdigest(),
                        native_task_kind="codex-desktop-turn", native_task_id=f"{target}:{turn['id']}:{item['id']}",
                        native_task_status="IDLE" if turn.get("status") == "completed" else "RUNNING", pid=os.getpid()))
                _atomic_json(attempt.root / "native-activity.json", {
                    "schema_version": TASK_ACTIVITY_SCHEMA, "adapter": endpoint.adapter,
                    "run_id": envelope.run_id, "cell_id": envelope.cell_id, "message_id": envelope.message_id,
                    "native_task_id": f"{target}:{turn['id']}:{item['id']}",
                    "status": "COMPLETED" if turn["status"] == "completed" else "RUNNING",
                    "sequence": request_id, "observed_at": utc_now(),
                    "last_event": {"kind": "DESKTOP_TURN_OBSERVED", "sequence": request_id}, "waiting_on": None})
                if turn.get("status") == "completed" or not wait_for_completion:
                    return DeliveryResult(RESULT_SCHEMA, envelope.message_id, envelope.run_id, endpoint.adapter,
                        "completed" if turn["status"] == "completed" else "started",
                        {"thread_id": target, "turn_id": turn["id"], "platform_item_id": item["id"], "turn_status": turn["status"]}, None,
                        ("started.json", "desktop-send.json", "desktop-readback.json"))
            now = time.monotonic()
            if proven is None and now >= deadline:
                raise AdapterError("CODEX_DESKTOP_READBACK_UNPROVED", "accepted send lacks exact native delivery/turn proof; do not resend blindly")
            if now >= finish_deadline:
                raise AdapterError("CODEX_TURN_TIMEOUT", "proven Desktop turn did not finish within the bound")
            time.sleep(min(.5, max(.001, (finish_deadline if proven else deadline) - now)))
    except TimeoutError as error:
        raise AdapterError("CODEX_RPC_TIMEOUT", "Desktop native tool timed out; accepted/start evidence remains separate") from error
    finally:
        client.close()
