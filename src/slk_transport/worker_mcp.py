"""Stdio MCP for the original Worker's explicit, host-authorized work events.

Startup and discovery never read a binding or record an action. The prepared
RoleHost remains the owner of caller validation, credentials, and state writes.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import sys
from typing import Any, Callable

from . import __version__
from .contracts import parse_delivery
from .role_host import load_role_host
from .worker_completion import CompletionError
from .worker_resume import require_live_action


EVENTS = ("WORK_STARTED", "D0_COMPLETED", "CANDIDATE_SUBMITTED")
# The installed native MCP SDK's supported legacy negotiation vocabulary.
PROTOCOL_VERSIONS = ("2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05", "2024-10-07")
TOOL_NAME = "slk_worker_action"
TOOL = {
    "name": TOOL_NAME,
    "description": "Record one explicit work event for the original bound Worker.",
    "inputSchema": {
        "type": "object",
        "properties": {
            "event": {"type": "string", "enum": list(EVENTS)},
            "details": {"type": "object", "default": {}},
        },
        "required": ["event"],
        "additionalProperties": False,
    },
}
SAFE_ERRORS = {
    "ROLE_HOST_BINDING_INVALID": "Prepared Worker binding is unavailable or changed.",
    "WORKER_ACTION_CALLER_UNPROVEN": "The original Worker invocation could not be verified.",
    "WORKER_ACTION_IDENTITY_MISMATCH": "Worker action identity does not match its bound source.",
    "WORKER_ACTION_WRITE_FAILED": "The explicit Worker event was not recorded.",
}


def _validate_action(event: Any, details: Any) -> None:
    if not isinstance(event, str) or event not in EVENTS or not isinstance(details, dict):
        raise ValueError("an explicit Worker event and details object are required")
    try:
        json.dumps(details, allow_nan=False)
    except (TypeError, ValueError, RecursionError) as exc:
        raise ValueError("Worker details must be a JSON object") from exc


def _reject_json_constant(_value: str) -> None:
    raise ValueError("nonstandard JSON constant")


def record(event: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    """Derive the exact source from the native host environment, never tool args."""
    details = {} if details is None else details
    _validate_action(event, details)
    native = Path(os.environ.get("SLK_NATIVE_ACTIVITY_PATH", ""))
    if not native.is_absolute() or native.name != "native-activity.json":
        raise CompletionError("WORKER_ACTION_CALLER_UNPROVEN", "no bound Worker invocation")
    source = native.parent
    try:
        endpoint = json.loads((source / "endpoint.json").read_text(encoding="utf-8"))
        if not isinstance(endpoint, dict):
            raise ValueError("Worker endpoint must be an object")
    except (OSError, UnicodeError, ValueError) as exc:
        raise CompletionError("ROLE_HOST_BINDING_INVALID", "prepared Worker endpoint is unavailable") from exc
    host = load_role_host(endpoint)
    if host is None:
        raise CompletionError("ROLE_HOST_BINDING_INVALID", "prepared Worker binding is missing")
    def pending(reason: str) -> dict[str, Any]:
        envelope = parse_delivery(endpoint, json.loads((source / "envelope.json").read_text(encoding="utf-8"))).envelope
        expected = {"adapter": endpoint["adapter"], "run_id": envelope.run_id,
                    "cell_id": envelope.cell_id, "message_id": envelope.message_id}
        if json.loads(os.environ.get("SLK_NATIVE_ACTIVITY_CONTEXT", "null")) != expected:
            raise CompletionError("WORKER_ACTION_CALLER_UNPROVEN", "Worker native invocation differs")
        return {"status": "WORKER_ACTION_PENDING", "retryable": True, "event_type": event,
                "source_message_id": envelope.message_id, "reason": reason,
                "next_action": "Retry the same bound MCP action after start/commit; do not busy-loop or redispatch."}
    if not (source / "started.json").is_file() and not any(
        (source / name).exists() for name in ("completed.json", "failed.json")
    ):
        return pending("NATIVE_START_PENDING")
    require_live_action(source)
    try:
        return host.record_worker_action(source, event, details, wait_for_commit=False)
    except CompletionError as exc:
        if exc.error_code != "ROLE_HOST_TOKEN_UNCONFIRMED":
            raise
        return pending("EXACT_TOKEN_COMMIT_PENDING")


def _error(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def respond(message: Any, action: Callable[..., Any] | None = None) -> dict[str, Any] | None:
    """Handle one JSON-RPC message without a general command or path surface."""
    if (not isinstance(message, dict) or message.get("jsonrpc") != "2.0"
        or not isinstance(message.get("method"), str)):
        return _error(None, -32600, "Invalid Request")
    if "id" not in message:
        return None  # Notifications, including malformed action notifications, never act.
    request_id = message["id"]
    if not isinstance(request_id, (str, int)) or isinstance(request_id, bool):
        return _error(None, -32600, "Invalid Request")
    params = message.get("params", {})
    if not isinstance(params, dict):
        return _error(request_id, -32602, "Invalid params")
    method = message["method"]
    if method == "initialize":
        requested = params.get("protocolVersion")
        result = {
            "protocolVersion": requested if requested in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0],
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "slk-original-worker-action", "version": __version__},
        }
    elif method == "ping":
        result = {}
    elif method == "tools/list":
        result = {"tools": [TOOL]}
    elif method == "tools/call":
        arguments = params.get("arguments", {})
        if (set(params) - {"name", "arguments", "_meta"} or params.get("name") != TOOL_NAME
            or ("_meta" in params and not isinstance(params["_meta"], dict))
            or not isinstance(arguments, dict) or "event" not in arguments
            or set(arguments) - {"event", "details"}):
            return _error(request_id, -32602, "Invalid params")
        event, details = arguments["event"], arguments.get("details", {})
        try:
            _validate_action(event, details)
        except ValueError:
            return _error(request_id, -32602, "Invalid params")
        try:
            recorded = (record if action is None else action)(event, details)
            result = {"content": [{"type": "text", "text": json.dumps(recorded, ensure_ascii=False, allow_nan=False)}]}
        except Exception as exc:
            code = exc.error_code if isinstance(exc, CompletionError) else None
            if not isinstance(code, str) or re.fullmatch(r"[A-Z][A-Z0-9_]{2,95}", code) is None:
                code = "WORKER_ACTION_REJECTED"
            text = f"{code}: {SAFE_ERRORS.get(code, 'Worker action could not be recorded.')}"
            result = {"isError": True, "content": [{"type": "text", "text": text}]}
    else:
        # The native SDK's disposable server/discover probe safely falls back to initialize.
        return _error(request_id, -32601, "Method not found")
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def main() -> int:
    """Serve newline JSON-RPC on stdio; no startup action or background work."""
    for stream in (sys.stdin, sys.stdout):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    for line in sys.stdin:
        try:
            message = json.loads(line, parse_constant=_reject_json_constant)
        except (ValueError, TypeError, RecursionError):
            response = _error(None, -32700, "Parse error")
        else:
            response = respond(message)
        if response is not None:
            sys.stdout.write(json.dumps(response, ensure_ascii=False, allow_nan=False) + "\n")
            sys.stdout.flush()
    return 0
