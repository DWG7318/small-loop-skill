from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path


MODE = sys.argv[1] if len(sys.argv) > 1 else "normal"


def emit(value: dict[str, object]) -> None:
    sys.stdout.write(json.dumps(value, separators=(",", ":")) + "\n")
    sys.stdout.flush()


for line in sys.stdin:
    message = json.loads(line)
    method = message.get("method")
    request_id = message.get("id")
    if method == "initialize":
        emit({"id": request_id, "result": {"serverInfo": {"name": "fake", "version": "1"}}})
    elif method == "initialized":
        continue
    elif method == "thread/start":
        cwd = Path(message["params"].get("cwd") or ".")
        run_id = cwd.parent.name
        emit({"id": request_id, "result": {"thread": {"id": f"thread-{run_id}"}}})
    elif method == "thread/resume":
        if MODE == "active-resume-conflict":
            emit({"id": request_id, "error": {"code": -32000, "message": "active writer conflict"}})
            continue
        thread_id = message["params"]["threadId"]
        if MODE == "wrong-thread":
            thread_id = "thr_wrong"
        emit({"id": request_id, "result": {"thread": {"id": thread_id}}})
    elif method == "thread/read":
        if MODE in {"active", "active-resume-conflict"}:
            status = {"type": "active", "activeFlags": []}
            turns = [{"id": "turn_active", "items": [], "status": "inProgress"}]
        elif MODE == "not-loaded":
            status = {"type": "notLoaded"}
            turns = []
        else:
            status = {"type": "idle"}
            turns = []
        read_thread_id = "thr_wrong" if MODE == "wrong-thread" else message["params"]["threadId"]
        emit(
            {
                "id": request_id,
                "result": {"thread": {"id": read_thread_id, "status": status, "turns": turns}},
            }
        )
    elif method == "turn/start":
        thread_id = message["params"]["threadId"]
        turn = {"id": "turn_exact", "items": [], "status": "inProgress"}
        emit({"id": request_id, "result": {"turn": turn}})
        if MODE != "no-start":
            emit({"method": "turn/started", "params": {"threadId": thread_id, "turn": turn}})
            terminal_status = "failed" if MODE == "failed-turn" else "completed"
            if MODE == "execute-command":
                text = message["params"]["input"][0]["text"]
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
