from __future__ import annotations

import json
import hashlib
import os
import re
import sys
import time
import uuid
from pathlib import Path


MODE = sys.argv[1]
arguments = sys.argv[2:]
instance_id = arguments[0]
prompt = arguments[-1]
runtime_root = Path(os.environ["DSH_RUNTIME_ROOT"])
session_root = runtime_root / "runs" / instance_id / "home" / "storages" / "session_projcache" / "sessions"
session_root.mkdir(parents=True, exist_ok=True)

if "--resume" in arguments:
    session_id = arguments[arguments.index("--resume") + 1]
else:
    session_id = f"session-{uuid.uuid4()}"
    (session_root / f"{session_id}.json").write_text("{}\n", encoding="utf-8")
    if MODE == "multiple-sessions":
        (session_root / f"session-{uuid.uuid4()}.json").write_text("{}\n", encoding="utf-8")

time.sleep(0.05)

match = re.search(r'<slk-transport-task path=(".*?") sha256=("[0-9a-f]{64}") />', prompt)
if not match:
    sys.exit(6)

task_path = Path(json.loads(match.group(1)))
task_sha256 = json.loads(match.group(2))
task_bytes = task_path.read_bytes()
if hashlib.sha256(task_bytes).hexdigest() != task_sha256:
    sys.exit(7)
task = json.loads(task_bytes)
result_path = Path(task["result_path"])
if MODE != "missing-result":
    if MODE == "delayed-terminal":
        time.sleep(0.35)
    envelope = task["envelope"]
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result = {
        "schema_version": "slk.worker-result/v1",
        "message_id": envelope["message_id"],
        "run_id": envelope["run_id"],
        "role_instance_id": envelope["receiver_role_instance_id"],
        "status": "completed",
        "candidate": {"kind": "none"},
        "next_payload": envelope["payload"],
    }
    temporary = result_path.with_suffix(".tmp")
    temporary.write_text(json.dumps(result), encoding="utf-8")
    os.replace(temporary, result_path)

print(json.dumps({"session_id": session_id, "result_path": str(result_path)}))
sys.exit(0)
