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
        thread_id = message["params"]["threadId"]
        if MODE == "wrong-thread":
            thread_id = "thr_wrong"
        emit({"id": request_id, "result": {"thread": {"id": thread_id}}})
    elif method == "thread/read":
        status = {"type": "active", "activeFlags": []} if MODE == "active" else {"type": "idle"}
        emit(
            {
                "id": request_id,
                "result": {"thread": {"id": message["params"]["threadId"], "status": status}},
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
