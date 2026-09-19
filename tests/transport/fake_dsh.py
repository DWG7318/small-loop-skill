from __future__ import annotations

import json
import os
import re
import sys
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

match = re.search(r"<slk-worker-result-path>(.*?)</slk-worker-result-path>", prompt)
envelope_match = re.search(r"<slk-transport-envelope>(.*?)</slk-transport-envelope>", prompt)
if not match or not envelope_match:
    sys.exit(6)

if MODE != "missing-result":
    envelope = json.loads(envelope_match.group(1))
    result_path = Path(json.loads(match.group(1)))
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

print(json.dumps({"session_id": session_id}))
sys.exit(0)
