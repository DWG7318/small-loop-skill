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
if "SLK_ROLE_CREDENTIAL" in os.environ or "SLK_OVERWATCHER_CREDENTIAL" in os.environ:
    sys.exit(8)
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

continuation_match = re.search(
    r'<slk-worker-continuation-task path=(".*?") sha256=("[0-9a-f]{64}") />',
    prompt,
)
if continuation_match:
    request_path = Path(json.loads(continuation_match.group(1)))
    request_sha256 = json.loads(continuation_match.group(2))
    request_bytes = request_path.read_bytes()
    if hashlib.sha256(request_bytes).hexdigest() != request_sha256:
        sys.exit(9)
    request = json.loads(request_bytes)
    result_path = Path(request["continuation_result_path"])
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_text(
        json.dumps(
            {
                "status": "CHECKER_STARTED",
                "run_id": request["run_id"],
                "source_message_id": request["source_message_id"],
                "candidate_message_id": str(uuid.uuid5(uuid.NAMESPACE_URL, request_sha256)),
            }
        ),
        encoding="utf-8",
    )
    print(json.dumps({"session_id": session_id, "continuation_result_path": str(result_path)}))
    sys.exit(0)

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
    outcome_modes = {
        "incomplete-git-blocker": ("incomplete", "GIT_COMMON_DIR_UNWRITABLE"),
        "blocked-result": ("blocked", "EXTERNAL_DEPENDENCY_BLOCKED"),
        "execution-failure-result": ("execution_failure", "COMMAND_EXECUTION_FAILED"),
        "timed-out-result": ("timed_out", "WORKER_BUDGET_EXHAUSTED"),
        "invalid-incomplete-candidate": ("incomplete", "GIT_COMMON_DIR_UNWRITABLE"),
    }
    if MODE in outcome_modes:
        outcome, cause = outcome_modes[MODE]
        result = {
            "schema_version": "slk.worker-result/v1",
            "message_id": envelope["message_id"],
            "run_id": envelope["run_id"],
            "role_instance_id": envelope["receiver_role_instance_id"],
            "status": outcome,
            "candidate": {"kind": "commit", "commit": "fake"}
            if MODE == "invalid-incomplete-candidate"
            else None,
            "next_payload": None,
            "blocker": {
                "phase": "git_commit",
                "cause": cause,
                "summary": "the exact Worker sandbox cannot write the Git common directory",
                "evidence": ["native.stderr.txt"],
            },
        }
    else:
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
