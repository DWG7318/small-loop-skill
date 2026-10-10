"""One invocation-bound MCP stdio bridge for the original OCRV Checker.

Indexed read-only originals and explicit D1 only. No command execution interface, credentials in tool arguments,
or background lifetime. OCRV starts this subprocess and closes stdin on exit.
"""
from __future__ import annotations

import json
import argparse
import os
import hashlib
import io
from pathlib import Path
import sys

TOOL_NAME = "slk_checker_decide"
TOOL = {
    "name": TOOL_NAME,
    "description": "Submit the original Checker's one explicit D1 decision for the entire frozen candidate and all CELL criteria, not a file/group verdict. Use existing cross-file tools and original evidence, including unchanged Shell/handshake seams required by CELL criteria. Do not submit once per group or repeat a prior whole-CELL decision; if you cannot establish all CELL goals, do not claim whole-CELL PASS. Native review ID proves identity, not whole-candidate completion. Finish this review and save actual reports and evidence first; make this decision and existing handoff your last action. The MCP reply is flushed before the original invocation ends. Do not continue reviewing after handoff. Optional message preserves actual findings/limitations without a report format. Counts, severity and exit status never determine D1. Reports remain independently delivered even if this action fails.",
    "inputSchema": {"type": "object", "properties": {
        "verdict": {"type": "string", "enum": ["PASS", "FAIL", "INCOMPLETE"]},
        "message": {"type": "string"}},
        "required": ["verdict"], "additionalProperties": False},
}
READ_TOOL = {
    "name": "slk_read_evidence",
    "description": "Read exact indexed runtime evidence outside Git after independent preliminary review. Index numbers come from the bound background, not arbitrary paths. Returns the full original by default, with SHA256, next_offset and eof. OCRV may choose offset/limit for a range; the tool imposes no content-length ceiling or automatic truncation. A requested range is not the whole original. No shell, writes, other invocation or unindexed file access.",
    "inputSchema": {"type": "object", "properties": {
        "index": {"type": "integer", "minimum": 0},
        "offset": {"type": "integer", "minimum": 0, "default": 0},
        "limit": {"type": "integer", "minimum": 1,
                  "description": "Optional character count chosen by OCRV, without an upper bound; omit to read through EOF."}},
        "required": ["index"], "additionalProperties": False},
}


def _bound_index() -> tuple[dict, dict]:
    receipt_path = Path(os.environ.get("SLK_NATIVE_START_RECEIPT", ""))
    path = Path(os.environ.get("SLK_CHECKER_EVIDENCE_INDEX", ""))
    if not path.is_absolute() or not receipt_path.is_absolute() or receipt_path.name != "native-start.received.json":
        raise ValueError("CHECKER_EVIDENCE_CALLER_UNPROVEN")
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != os.environ.get("SLK_CHECKER_EVIDENCE_INDEX_SHA256"):
        raise ValueError("CHECKER_EVIDENCE_INDEX_CHANGED")
    index = json.loads(raw)
    receipt = json.loads(receipt_path.read_text(encoding="utf-8-sig"))
    if (any(index.get(key) != receipt[key] for key in (
        "run_id", "cell_id", "message_id", "native_request_sha256"))
        or index.get("native_task_id") != receipt["native_task"]["id"]):
        raise ValueError("CHECKER_EVIDENCE_INVOCATION_MISMATCH")
    return index, receipt


def read_evidence(index: int, offset: int = 0, limit: int | None = None) -> dict:
    if (any(type(value) is not int for value in (index, offset))
        or index < 0 or offset < 0
        or (limit is not None and (type(limit) is not int or limit < 1))):
        raise ValueError("invalid evidence index/character offset/limit")
    bound, _ = _bound_index()
    if index >= len(bound["evidence"]):
        raise ValueError("evidence index is not registered")
    item = bound["evidence"][index]
    with Path(item["path"]).open("rb") as stream:
        before = os.fstat(stream.fileno())
        digest = hashlib.sha256()
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
        if digest.hexdigest() != item["sha256"]:
            raise ValueError("CHECKER_EVIDENCE_BYTES_CHANGED")
        stream.seek(0)
        text_stream = io.TextIOWrapper(stream, encoding="utf-8-sig", errors="strict", newline="")
        remaining = offset
        while remaining:
            skipped = text_stream.read(min(remaining, 4096))
            if not skipped:
                raise ValueError("evidence offset exceeds original")
            remaining -= len(skipped)
        # UTF-8 characters cannot outnumber file bytes. Requests beyond the
        # actual file read to EOF without overflowing Python's read size.
        text = text_stream.read(-1 if limit is None else min(limit, before.st_size))
        eof = not text_stream.read(1)
        after = os.fstat(stream.fileno())
        if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            raise ValueError("CHECKER_EVIDENCE_BYTES_CHANGED")
    return {"index": index, "path": item["path"], "sha256": item["sha256"],
            "text": text, "next_offset": offset + len(text), "eof": eof}


def _publish_native_process() -> None:
    """Original stdio client parent, not the launcher PID or an engineering action."""
    from slk_checker_adapter import _process_creation_time, _process_parents, _sha256, _write_json_atomic
    index, receipt = _bound_index()
    source = Path(os.environ["SLK_NATIVE_START_RECEIPT"])
    launcher = receipt["process"]
    if _process_creation_time(launcher["pid"]) != launcher["creation_time"]:
        raise ValueError("native launcher identity changed")
    pid = os.getppid()  # official OCRV stdio MCP client is the direct parent
    parents, current = _process_parents(), pid
    visited = set()
    while current != launcher["pid"]:
        if current in visited or current not in parents:
            raise ValueError("native MCP parent is not under this launcher")
        visited.add(current)
        current = parents.get(current, 0)
    path = source.with_name("ocrv-native-process.json")
    value = {"schema_version": "slk.ocrv-native-process/v1",
        **{key: receipt[key] for key in ("run_id", "cell_id", "message_id", "native_request_sha256")},
        "native_task_id": index["native_task_id"], "native_start_sha256": _sha256(source),
        "index_path": os.environ["SLK_CHECKER_EVIDENCE_INDEX"],
        "index_sha256": os.environ["SLK_CHECKER_EVIDENCE_INDEX_SHA256"],
        "launcher_process": launcher, "process": {"pid": pid, "creation_time": _process_creation_time(pid)}}
    if path.exists():
        if json.loads(path.read_text(encoding="utf-8")) != value:
            raise ValueError("native process observation conflicts with original")
        return
    _write_json_atomic(path, value)


def _publish_completion(request: dict, response: dict) -> None:
    """Only after the explicit host action returns AND its MCP reply is flushed."""
    if not isinstance(request, dict):
        return
    params = request.get("params", {})
    if (not isinstance(params, dict) or request.get("method") != "tools/call" or params.get("name") != TOOL_NAME
        or response.get("result", {}).get("isError") or "result" not in response):
        return
    result = json.loads(response["result"]["content"][0]["text"])
    if result.get("status") != "CHECKER_D1_RECORDED":
        return
    from slk_checker_adapter import _process_creation_time, _sha256, _write_json_atomic
    index, receipt = _bound_index()
    source = Path(os.environ["SLK_NATIVE_START_RECEIPT"]).parent
    decision = source / "role-host" / "checker-decision.json"
    if Path(result["decision_path"]).resolve() != decision.resolve():
        raise ValueError("CHECKER_COMPLETION_DECISION_MISMATCH")
    pid = os.getppid()  # official OCRV stdio MCP client starts us directly
    _write_json_atomic(Path(os.environ["SLK_CHECKER_EVIDENCE_INDEX"]).with_name("review-completed.json"), {
        "schema_version": "slk.ocrv-completion/v1",
        **{key: receipt[key] for key in ("run_id", "cell_id", "message_id", "native_request_sha256")},
        "native_task_id": index["native_task_id"],
        "native_start_sha256": _sha256(source / "native-start.received.json"),
        "review_process": {"pid": pid, "creation_time": _process_creation_time(pid)},
        "decision_path": str(decision), "decision_sha256": _sha256(decision),
        "verdict": result["verdict"],
    })


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
            "serverInfo": {"name": "slk-original-checker-decision", "version": "4.4.4"}}
    elif method == "ping":
        response["result"] = {}
    elif method == "tools/list":
        response["result"] = {"tools": [TOOL, READ_TOOL]}
    elif method == "tools/call":
        try:
            arguments = params.get("arguments", {})
            if params.get("name") == READ_TOOL["name"]:
                if (not isinstance(arguments, dict) or "index" not in arguments
                    or set(arguments) - {"index", "offset", "limit"}):
                    raise ValueError("only indexed evidence and optional character ranges are supported")
                result = read_evidence(**arguments)
                response["result"] = {"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}]}
                return response
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
    sys.stdin.reconfigure(encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--transport", required=True, type=Path)
    package = parser.parse_args().transport
    if not package.is_absolute() or not package.is_file() or package.suffix != ".pyz":
        parser.error("--transport must name the installed absolute slk-transport.pyz")
    sys.path.insert(0, str(package))
    try:
        _publish_native_process()
    except (ValueError, OSError, KeyError, TypeError) as exc:
        print(f"CHECKER_NATIVE_PROCESS_UNCONFIRMED: {exc}", file=sys.stderr, flush=True)
    for line in sys.stdin:
        value = {}
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
            try:
                _publish_completion(value, response)
            except (ValueError, OSError, KeyError, TypeError) as exc:
                print(f"CHECKER_COMPLETION_UNCONFIRMED: {exc}", file=sys.stderr, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
