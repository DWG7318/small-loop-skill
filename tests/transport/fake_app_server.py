from __future__ import annotations

import json
import hashlib
import re
import subprocess
import sys
from pathlib import Path


MODE = sys.argv[1] if len(sys.argv) > 1 else "normal"


def emit(value: dict[str, object]) -> None:
    sys.stdout.write(json.dumps(value, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def read_task(params: dict[str, object]) -> str:
    """The fake native receiver independently checks the existing material contract."""
    text = params["input"][0]["text"]
    if not text.startswith("SLK cross-Agent delivery. Read the complete UTF-8 JSON material "):
        return text  # Historical inline turns, including the drill bootstrap, stay supported.
    reference = json.loads(text.split("\n", 1)[1])
    path = Path(reference["path"])
    try:
        if (set(reference) != {"path", "bytes", "sha256", "message_id", "run_id", "cell_id", "payload_sha256"}
            or not path.is_absolute() or path.name != "desktop-material.json"):
            raise ValueError("reference path or fields changed")
        data = path.read_bytes()
        if (type(reference["bytes"]) is not int or reference["bytes"] != len(data)
            or reference["sha256"] != hashlib.sha256(data).hexdigest()):
            raise ValueError("byte count or SHA-256 changed")
        material = json.loads(data)
        if (set(material) != {"schema_version", "envelope", "prompt"}
            or material["schema_version"] != "slk.desktop-material/v1"
            or not isinstance(material["prompt"], str)):
            raise ValueError("schema or complete task is invalid")
        envelope = material["envelope"]
        if (envelope.get("receiver_role") != "supervisor"
            or reference["message_id"] != params.get("clientUserMessageId")
            or any(reference[key] != envelope.get(key) for key in
                ("message_id", "run_id", "cell_id", "payload_sha256"))):
            raise ValueError("Run/CELL/message/role identity changed")
        payload_bytes = json.dumps(envelope["payload"], ensure_ascii=False,
            sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
        if hashlib.sha256(payload_bytes).hexdigest() != envelope["payload_sha256"]:
            raise ValueError("envelope payload hash changed")
        return material["prompt"]
    except (OSError, ValueError, TypeError, KeyError) as error:
        raise ValueError(f"material rejected at {path.resolve()}: {error}") from error


for line in sys.stdin:
    message = json.loads(line)
    method = message.get("method")
    request_id = message.get("id")
    if method == "initialize":
        if MODE == "initialize-rpc-timeout":
            continue
        if MODE in {"initialize-writer-conflict", "initialize-writer-flood-conflict"}:
            if MODE == "initialize-writer-flood-conflict":
                emit({"method": "diagnostic", "params": {"blob": "x" * (2 * 1024 * 1024)}})
            emit(
                {
                    "id": request_id,
                    "error": {
                        "code": -32000,
                        "message": "thread-store conflict: thread thr_exact already has an active writer",
                    },
                }
            )
            continue
        emit({"id": request_id, "result": {"serverInfo": {"name": "fake", "version": "1"}}})
    elif method == "initialized":
        continue
    elif method == "thread/start":
        cwd = Path(message["params"].get("cwd") or ".")
        run_id = cwd.parent.name
        emit({"id": request_id, "result": {"thread": {"id": f"thread-{run_id}"}}})
    elif method == "thread/resume":
        if MODE in {"active-resume-conflict", "resume-already-active-writer"}:
            message = (
                "already has an active writer"
                if MODE == "resume-already-active-writer"
                else "active writer conflict"
            )
            if MODE == "resume-already-active-writer":
                (Path.cwd() / ".fake-active-writer").write_text("active", encoding="utf-8")
            emit({"id": request_id, "error": {"code": -32000, "message": message}})
            continue
        thread_id = message["params"]["threadId"]
        if MODE == "wrong-thread":
            thread_id = "thr_wrong"
        emit({"id": request_id, "result": {"thread": {"id": thread_id}}})
    elif method == "thread/read":
        if MODE == "metadata-rpc-timeout":
            continue
        if MODE in {
            "active",
            "active-resume-conflict",
            "active-paginated",
            "active-paginated-omitted",
            "active-paginated-missing",
            "active-paginated-multiple",
            "long-history-active",
        }:
            status = (
                {"type": "notLoaded"}
                if MODE == "long-history-active"
                else {"type": "active", "activeFlags": []}
            )
            turns = [] if MODE.startswith("active-paginated") else [
                {"id": "turn_active", "items": [], "status": "inProgress"}
            ]
        elif MODE == "resume-already-active-writer" and (
            request_id > 2 or (Path.cwd() / ".fake-active-writer").is_file()
        ):
            status = {"type": "active", "activeFlags": []}
            turns = [{"id": "turn_active", "items": [], "status": "inProgress"}]
        elif MODE == "resume-already-active-writer":
            status = {"type": "notLoaded"}
            turns = []
        elif MODE == "not-loaded":
            status = {"type": "notLoaded"}
            turns = []
        else:
            status = {"type": "idle"}
            turns = []
        read_thread_id = "thr_wrong" if MODE == "wrong-thread" else message["params"]["threadId"]
        thread = {"id": read_thread_id, "status": status, "turns": turns}
        if MODE == "active-paginated-omitted" or message["params"].get("includeTurns") is False:
            thread.pop("turns")
        emit({"id": request_id, "result": {"thread": thread}})
    elif method == "thread/turns/list":
        cursor = message["params"].get("cursor")
        if MODE in {
            "active",
            "active-resume-conflict",
            "resume-already-active-writer",
            "long-history-active",
        } and cursor is None:
            emit(
                {
                    "id": request_id,
                    "result": {
                        "data": [{"id": "turn_active", "items": [], "status": "inProgress"}],
                        "nextCursor": None,
                    },
                }
            )
        elif MODE in {"active-paginated", "active-paginated-omitted", "active-paginated-multiple"} and cursor is None:
            emit(
                {
                    "id": request_id,
                    "result": {
                        "data": [{"id": "turn_old", "items": [], "status": "completed"}],
                        "nextCursor": "active-page-2",
                    },
                }
            )
        elif MODE in {"active-paginated", "active-paginated-omitted"} and cursor == "active-page-2":
            emit(
                {
                    "id": request_id,
                    "result": {
                        "data": [{"id": "turn_active", "items": [], "status": "inProgress"}],
                        "nextCursor": None,
                    },
                }
            )
        elif MODE == "active-paginated-multiple" and cursor == "active-page-2":
            emit(
                {
                    "id": request_id,
                    "result": {
                        "data": [
                            {"id": "turn_active", "items": [], "status": "inProgress"},
                            {"id": "turn_other", "items": [], "status": "active"},
                        ],
                        "nextCursor": None,
                    },
                }
            )
        else:
            emit({"id": request_id, "result": {"data": [], "nextCursor": None}})
    elif method == "turn/start":
        if MODE == "turn-start-rpc-timeout":
            continue
        try:
            text = read_task(message["params"])
        except (ValueError, TypeError, KeyError) as error:
            emit({"id": request_id, "error": {"code": -32000, "message": str(error)}})
            continue
        thread_id = message["params"]["threadId"]
        turn = {"id": "turn_exact", "items": [], "status": "inProgress"}
        emit({"id": request_id, "result": {"turn": turn}})
        if MODE != "no-start":
            emit({"method": "turn/started", "params": {"threadId": thread_id, "turn": turn}})
            terminal_status = "failed" if MODE == "failed-turn" else "completed"
            if MODE == "execute-command":
                match = re.search(r"<slk-supervisor-command>(.*?)</slk-supervisor-command>", text)
                if match:
                    command = json.loads(match.group(1))
                    completed = subprocess.run(
                        command,
                        cwd=message["params"].get("cwd"),
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        check=False,
                    )
                    terminal_status = "completed" if completed.returncode == 0 else "failed"
            emit(
                {
                    "method": "turn/completed",
                    "params": {
                        "threadId": thread_id,
                        "turn": {"id": "turn_exact", "items": [], "status": terminal_status},
                    },
                }
            )
    elif method == "turn/steer":
        thread_id = message["params"]["threadId"]
        if message["params"].get("expectedTurnId") != "turn_active":
            emit({"id": request_id, "error": {"code": -32000, "message": "wrong turn"}})
        else:
            emit(
                {
                    "id": request_id,
                    "result": {"turn": {"id": "turn_active", "items": [], "status": "inProgress"}},
                }
            )
