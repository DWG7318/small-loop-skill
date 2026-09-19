from __future__ import annotations

import argparse
import hashlib
import json
import sys
import uuid
from pathlib import Path


parser = argparse.ArgumentParser()
parser.add_argument("mode")
parser.add_argument("--request", required=True, type=Path)
parser.add_argument("--output", required=True, type=Path)
args = parser.parse_args()

request = json.loads(args.request.read_text(encoding="utf-8"))
session_id = None if args.mode == "missing-session" else f"ocrv-session-{uuid.uuid4()}"
result = {
    "schema_version": "slk.ocrv-d1-result/v1",
    "run_id": request["run_id"],
    "cell_id": request["cell_id"],
    "review_invocation_id": str(uuid.uuid4()),
    "verdict": "PASS",
    "reason_codes": ["OCR_COMPLETE_ZERO_FINDINGS"],
    "findings": [],
    "review": {
        "status": "complete",
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
sys.exit(0)
