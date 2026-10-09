"""One invocation-bound MCP stdio action for the original OCRV Checker.

No report parsing, command execution interface, credentials in tool arguments,
or background lifetime. OCRV starts this subprocess and closes stdin on exit.
"""
from __future__ import annotations

import json
import argparse
import os
from pathlib import Path
import sys

TOOL_NAME = "slk_checker_decide"
TOOL = {
    "name": TOOL_NAME,
    "description": "Submit the original Checker's one explicit D1 decision for the entire frozen candidate and all CELL criteria, not a file/group verdict. Use existing cross-file tools and original evidence before deciding. Do not submit once per group or repeat a prior whole-CELL decision; if you cannot establish all CELL goals, do not claim whole-CELL PASS. Native review ID proves identity, not whole-candidate completion. Execute the existing handoff; optional message preserves actual findings/limitations without a report format. Counts, severity and exit status never determine D1. Reports remain independently delivered even if this action fails.",
    "inputSchema": {"type": "object", "properties": {
        "verdict": {"type": "string", "enum": ["PASS", "FAIL", "INCOMPLETE"]},
        "message": {"type": "string"}},
        "required": ["verdict"], "additionalProperties": False},
}


def record(verdict: str, message: str | None = None) -> dict:
    from slk_transport.role_host import load_role_host
    receipt = Path(os.environ.get("SLK_NATIVE_START_RECEIPT", ""))
    if not receipt.is_absolute() or receipt.name != "native-start.received.json":
        raise ValueError("CHECKER_DECISION_CALLER_UNPROVEN: no bound native invocation")
    source = receipt.parent
    endpoint = json.loads((source / "endpoint.json").read_text(encoding="utf-8-sig"))
    host = load_role_host(endpoint)
    if host is None:
        raise ValueError("ROLE_HOST_BINDING_INVALID: no prepared host")
    return host.submit_checker_decision(source, verdict, message)


def respond(message: dict, action=record) -> dict | None:
    """MCP JSON-RPC framing, not an Agent or a general command dispatcher."""
    if "id" not in message:
        return None
    response = {"jsonrpc": "2.0", "id": message["id"]}
    method, params = message.get("method"), message.get("params", {})
    if not isinstance(params, dict):
        response["error"] = {"code": -32602, "message": "Invalid params"}
        return response
    if method == "initialize":
        requested = params.get("protocolVersion")
        response["result"] = {"protocolVersion": requested if requested in {
            "2024-11-05", "2025-03-26", "2025-06-18"} else "2025-03-26",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "slk-original-checker-decision", "version": "4.4.2"}}
    elif method == "ping":
        response["result"] = {}
    elif method == "tools/list":
        response["result"] = {"tools": [TOOL]}
    elif method == "tools/call":
        try:
            arguments = params.get("arguments", {})
            if (params.get("name") != TOOL_NAME or not isinstance(arguments, dict)
                or "verdict" not in arguments or set(arguments) - {"verdict", "message"}):
                raise ValueError("only the bound explicit Checker decision is supported")
            verdict = arguments["verdict"]
            if verdict not in {"PASS", "FAIL", "INCOMPLETE"}:
                raise ValueError("an explicit Checker verdict is required")
            if "message" in arguments:
                if not isinstance(arguments["message"], str):
                    raise ValueError("message must be original text")
                result = action(verdict, message=arguments["message"])
            else:
                result = action(verdict)
            response["result"] = {"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}]}
        except (ValueError, OSError, KeyError, TypeError) as exc:
            response["result"] = {"isError": True, "content": [{"type": "text", "text": str(exc)}]}
    else:
        response["error"] = {"code": -32601, "message": "Method not found"}
    return response


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--transport", required=True, type=Path)
    package = parser.parse_args().transport
    if not package.is_absolute() or not package.is_file() or package.suffix != ".pyz":
        parser.error("--transport must name the installed absolute slk-transport.pyz")
    sys.path.insert(0, str(package))
    for line in sys.stdin:
        try:
            value = json.loads(line)
            if not isinstance(value, dict) or value.get("jsonrpc") != "2.0":
                raise ValueError("Invalid Request")
            response = respond(value)
        except (ValueError, TypeError) as exc:
            response = {"jsonrpc": "2.0", "id": None,
                        "error": {"code": -32700, "message": str(exc)}}
        if response is not None:
            print(json.dumps(response, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
