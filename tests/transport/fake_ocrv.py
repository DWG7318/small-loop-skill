from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
import uuid
from pathlib import Path


parser = argparse.ArgumentParser()
parser.add_argument("mode")
parser.add_argument("--slk-worker-recovery", action="store_true")
parser.add_argument("--request", required=True, type=Path)
parser.add_argument("--output", required=True, type=Path)
args = parser.parse_args()

if "SLK_ROLE_CREDENTIAL" in os.environ or "SLK_OVERWATCHER_CREDENTIAL" in os.environ:
    sys.exit(8)

request = json.loads(args.request.read_text(encoding="utf-8"))
if args.slk_worker_recovery:
    source_root = Path(request["source_attempt_root"])
    source_envelope = json.loads((source_root / "envelope.json").read_text(encoding="utf-8"))
    source_started = json.loads((source_root / "started.json").read_text(encoding="utf-8"))
    result = {
        "schema_version": "slk.ocrv-worker-recovery-result/v1",
        "method_version": "4.2.7",
        "status": "CHECKER_STARTED",
        "run_id": request["run_id"],
        "cell_id": request["cell_id"],
        "source_message_id": source_envelope["message_id"],
        "worker_session_id": source_started["session_id"],
        "checker_role_instance_id": request["checker_role_instance_id"],
        "checker_endpoint_version": request["checker_endpoint_version"],
        "checker_authenticated": True,
        "authorized_recovery": True,
        "recovery_invocation_id": request["recovery_invocation_id"],
        "request_sha256": hashlib.sha256(args.request.read_bytes()).hexdigest(),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result), encoding="utf-8")
    sys.exit(0)
if args.mode == "delayed-terminal":
    time.sleep(0.35)
expected_request_fields = {
    "schema_version",
    "run_id",
    "cell_id",
    "repository",
    "candidate",
    "cell_goal",
    "d1_criteria",
    "evidence_files",
}
if set(request) != expected_request_fields:
    print("SLK_OCRV_REQUEST_INVALID: unknown or missing request field", file=sys.stderr)
    sys.exit(4)
session_id = None if args.mode == "missing-session" else f"ocrv-session-{uuid.uuid4()}"
verdict = "INCOMPLETE" if args.mode == "incomplete" else "PASS"
result = {
    "schema_version": "slk.ocrv-d1-result/v1",
    "run_id": request["run_id"],
    "cell_id": request["cell_id"],
    "review_invocation_id": str(uuid.uuid4()),
    "verdict": verdict,
    "reason_codes": ["OCR_STATUS_NOT_COMPLETE"] if verdict == "INCOMPLETE" else ["OCR_COMPLETE_ZERO_FINDINGS"],
    "findings": [],
    "review": {
        "status": "skipped" if verdict == "INCOMPLETE" else "complete",
        "provider": "dashscope-tokenplan",
        "model": "qwen3.8-max",
        "session_id": session_id,
        "exit_code": 0,
    },
    "evidence": [],
    "request_sha256": hashlib.sha256(args.request.read_bytes()).hexdigest(),
    "artifacts": {},
}
args.output.parent.mkdir(parents=True, exist_ok=True)
args.output.write_text(json.dumps(result), encoding="utf-8")
sys.exit(3 if verdict == "INCOMPLETE" else 0)
