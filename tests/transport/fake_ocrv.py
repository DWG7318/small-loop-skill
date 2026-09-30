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
parser.add_argument("--preflight", action="store_true")
parser.add_argument("--request", required=True, type=Path)
parser.add_argument("--output", required=True, type=Path)
args = parser.parse_args()

if "SLK_ROLE_CREDENTIAL" in os.environ or "SLK_OVERWATCHER_CREDENTIAL" in os.environ:
    sys.exit(8)

request = json.loads(args.request.read_text(encoding="utf-8"))
invocations = Path(request.get("repository", args.output.parent)) / ".fake-ocrv-invocations.jsonl"
with invocations.open("a", encoding="utf-8") as stream:
    stream.write(json.dumps({"preflight": args.preflight, "request": str(args.request)}) + "\n")
if args.slk_worker_recovery:
    source_root = Path(request["source_attempt_root"])
    source_envelope = json.loads((source_root / "envelope.json").read_text(encoding="utf-8"))
    source_started = json.loads((source_root / "started.json").read_text(encoding="utf-8"))
    result = {
        "schema_version": "slk.ocrv-worker-recovery-result/v1",
        "method_version": "4.3.4",
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
expected_request_fields_v1 = {
    "schema_version",
    "run_id",
    "cell_id",
    "repository",
    "candidate",
    "cell_goal",
    "d1_criteria",
    "evidence_files",
}
expected_request_fields_v2 = expected_request_fields_v1 | {"review_scope", "capacity"}
if frozenset(request) not in {
    frozenset(expected_request_fields_v1),
    frozenset(expected_request_fields_v2),
}:
    print("SLK_OCRV_REQUEST_INVALID: unknown or missing request field", file=sys.stderr)
    sys.exit(4)
if args.preflight:
    changed_paths: list[str] = []
    for evidence_path in request["evidence_files"]:
        value = json.loads(Path(evidence_path).read_text(encoding="utf-8"))
        for path in value.get("next_payload", {}).get("changed_paths", []):
            if path not in changed_paths:
                changed_paths.append(path)
    scope = request.get("review_scope", {})
    selected = (
        list(scope.get("include_paths", []))
        if scope.get("include_paths") or scope.get("exclude_paths")
        else changed_paths
    )
    if args.mode == "scope-leak" and scope.get("include_paths"):
        selected = changed_paths
    background_chars = len(request["cell_goal"]) + sum(map(len, request["d1_criteria"])) + 256
    preflight_incomplete = (
        args.mode == "preflight-incomplete"
        or background_chars > request.get("capacity", {}).get("max_background_characters", 8_000)
    )
    result = {
        "schema_version": "slk.ocrv-d1-preflight/v1",
        "status": "INCOMPLETE" if preflight_incomplete else "READY",
        "run_id": request["run_id"],
        "cell_id": request["cell_id"],
        "request_sha256": hashlib.sha256(args.request.read_bytes()).hexdigest(),
        "background": {
            "characters": background_chars,
            "bytes": background_chars,
            "evidence_bytes": sum(Path(path).stat().st_size for path in request["evidence_files"]),
            "sha256": "a" * 64,
        },
        "preview": {
            "exit_code": 0,
            "selected_paths": selected,
            "inventory": [
                {
                    "path": path,
                    "status": "modified",
                    "insertions": 10,
                    "deletions": 2,
                    "will_review": path in selected,
                    "exclude_reason": None if path in selected else "cli_exclude",
                }
                for path in changed_paths
            ],
            "stdout_sha256": "b" * 64,
            "stderr_sha256": "c" * 64,
        },
        "scope": scope,
        "capabilities": {"available": ["ocrv-preview"], "selected": [], "invocations": []},
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result), encoding="utf-8")
    sys.exit(3 if preflight_incomplete else 0)
if args.mode == "timeout-second" and "segment 2/" in request["cell_goal"]:
    time.sleep(0.35)
session_id = None if args.mode == "missing-session" else f"ocrv-session-{uuid.uuid4()}"
is_first_segment = "segment 1/" in request["cell_goal"]
segment_sentinel = (
    "SEGMENT_FULL_RESULT_MUST_NOT_ENTER_AGGREGATE_" + "Z" * 4_096
    if "segment " in request["cell_goal"]
    else ""
)
verdict = (
    "FAIL"
    if args.mode == "blocking-first" and is_first_segment
    else "INCOMPLETE"
    if args.mode == "incomplete"
    else "PASS"
)
findings = (
    [{"severity": "HIGH", "message": "candidate violates the frozen criterion"}]
    if verdict == "FAIL"
    else []
)
result = {
    "schema_version": "slk.ocrv-d1-result/v1",
    "run_id": request["run_id"],
    "cell_id": request["cell_id"],
    "review_invocation_id": str(uuid.uuid4()),
    "verdict": verdict,
    "reason_codes": (
        ["OCR_STATUS_NOT_COMPLETE"]
        if verdict == "INCOMPLETE"
        else ["OCR_FINDINGS_PRESENT"]
        if verdict == "FAIL"
        else ["OCR_COMPLETE_ZERO_FINDINGS"]
    ),
    "findings": findings,
    "review": {
        "status": "skipped" if verdict == "INCOMPLETE" else "complete",
        "provider": "dashscope-tokenplan",
        "model": "qwen3.8-max",
        "session_id": session_id,
        "exit_code": 0,
    },
    "evidence": ([{"raw_segment_output": segment_sentinel}] if segment_sentinel else []),
    "request_sha256": hashlib.sha256(args.request.read_bytes()).hexdigest(),
    "artifacts": {},
}
args.output.parent.mkdir(parents=True, exist_ok=True)
args.output.write_text(json.dumps(result), encoding="utf-8")
sys.exit(3 if verdict == "INCOMPLETE" else 2 if verdict == "FAIL" else 0)
