"""Frozen OCRV compression recovery through the existing management-return route."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Mapping

from .evidence import Attempt


SCHEMA = "slk.ocrv-context-recovery-plan/v1"
FIELDS = {"schema_version", "run_id", "cell_id", "candidate_message_id",
          "source_d1_incomplete_event_id", "sources", "groups"}
SOURCE_FIELDS = {"request", "result", "raw_review", "session_record"}
COMPRESSION_REASON = "stopped because context compression exceeded its threshold"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError("context recovery source is not an object")
    return value


def identities(value: object) -> dict[str, dict[str, str]]:
    if not isinstance(value, list):
        raise ValueError("context coverage is not an array")
    found: dict[str, dict[str, str]] = {}
    ids, fingerprints = set(), set()
    for item in value:
        if not isinstance(item, dict):
            raise ValueError("context coverage item is not an object")
        identity = {k: item.get(k) for k in ("item_id", "path", "fingerprint")}
        path = identity["path"]
        if (not isinstance(path, str) or not path or path in found
            or Path(path).is_absolute() or ".." in Path(path).parts
            or any(not isinstance(identity[k], str) or re.fullmatch(r"[0-9a-f]{64}", identity[k]) is None
                   for k in ("item_id", "fingerprint"))
            or identity["item_id"] in ids or identity["fingerprint"] in fingerprints):
            raise ValueError("context coverage identity is missing, duplicated or unsafe")
        found[path] = identity
        ids.add(identity["item_id"]); fingerprints.add(identity["fingerprint"])
    return found


def validate(plan: Mapping[str, Any], request: Mapping[str, Any], payload: Mapping[str, Any]) -> dict[str, Any]:
    if (set(plan) != FIELDS or plan.get("schema_version") != SCHEMA
        or any(plan.get(k) != request.get(k) for k in ("run_id", "cell_id"))
        or any(plan.get(k) != payload.get(k) for k in
               ("candidate_message_id", "source_d1_incomplete_event_id"))
        or not isinstance(plan.get("sources"), dict) or set(plan["sources"]) != SOURCE_FIELDS):
        raise ValueError("context recovery plan identity or source set is invalid")
    paths = {}
    for key, ref in plan["sources"].items():
        if (not isinstance(ref, dict) or set(ref) != {"path", "sha256"}
            or not isinstance(ref["path"], str) or not Path(ref["path"]).is_absolute()):
            raise ValueError("context source reference is invalid")
        path = Path(ref["path"]).resolve()
        if not path.is_file() or digest(path) != ref["sha256"]:
            raise ValueError("context source is missing or changed")
        paths[key] = path
    old, result, raw = (read(paths[k]) for k in ("request", "result", "raw_review"))
    stable = {"schema_version", "run_id", "cell_id", "repository", "candidate", "cell_goal", "d1_criteria",
              "evidence_files", "review_scope"}
    if (any(old.get(k) != request.get(k) for k in stable)
        or request.get("candidate", {}).get("kind") != "commit"
        or result.get("schema_version") != "slk.ocrv-d1-result/v1"
        or result.get("verdict") != "INCOMPLETE" or result.get("request_sha256") != digest(paths["request"])
        or any(result.get(k) != request.get(k) for k in ("run_id", "cell_id"))
        or Path(str(result.get("artifacts", {}).get("raw_review", ""))).resolve() != paths["raw_review"]):
        raise ValueError("context candidate, criteria, scope or original INCOMPLETE result changed")
    manifest = raw.get("manifest")
    if (not isinstance(manifest, dict) or manifest.get("schema_version") != "ocr.run-manifest/v1"
        or manifest.get("operation") != "review" or manifest.get("terminal_state") != "partial"
        or manifest.get("run_id") != raw.get("session_id")
        or result.get("review", {}).get("session_id") != raw.get("session_id")
        or raw.get("status") != "partial"
        or manifest.get("input", {}).get("mode") != "commit"
        or manifest.get("input", {}).get("resolved_head") != request["candidate"]["commit"]
        or any(manifest.get("execution", {}).get(k) != v for k, v in
               {"provider": "dashscope-tokenplan", "model": "qwen3.8-max"}.items())
        or not isinstance(raw.get("comments"), list)
        or any(not isinstance(x, dict) or str(x.get("severity", "")).upper()
               not in {"INFO", "LOW", "MEDIUM", "HIGH", "BLOCKER", "CRITICAL"} for x in raw["comments"])):
        raise ValueError("context source is not the frozen native partial review")
    coverage = manifest.get("coverage", {})
    selected = identities(coverage.get("selected"))
    done = identities(coverage.get("completed"))
    reused = identities(coverage.get("reused", []))
    failed = identities(coverage.get("failed"))
    if (not selected or not failed or not done or coverage.get("waived")
        or set(done) & set(reused) or (set(done) | set(reused)) & set(failed)
        or {**done, **reused, **failed} != selected
        or any(x.get("reason") != COMPRESSION_REASON for x in coverage["failed"])):
        raise ValueError("context source coverage is not a compression-only full-scope partition")
    checkpoints, terminal = {}, []
    # Stream the native log locally; LLM request/response bodies never enter the plan or model context.
    with paths["session_record"].open(encoding="utf-8-sig") as stream:
        for line in stream:
            if not line.endswith("\n"):
                raise ValueError("context native checkpoint log is torn")
            row = json.loads(line)
            if not isinstance(row, dict):
                raise ValueError("context native checkpoint record is invalid")
            if row.get("type") in {"review_item_done", "review_item_reused"}:
                checkpoints[row.get("fingerprint")] = row
            elif row.get("type") == "review_item_failed":
                checkpoints.pop(row.get("fingerprint"), None)
            elif row.get("type") == "session_end":
                terminal.append(row)
    if len(terminal) != 1 or terminal[0].get("run_manifest") != manifest:
        raise ValueError("context native terminal manifest changed")
    for item in [*done.values(), *reused.values()]:
        checkpoint = checkpoints.get(item["fingerprint"], {})
        if (checkpoint.get("sessionId") != raw["session_id"] or checkpoint.get("filePath") != item["path"]
            # OCRV's native writer omits `comments` for a legitimate zero-finding checkpoint.
            or ("comments" in checkpoint and not isinstance(checkpoint["comments"], list))):
            raise ValueError("context completed item has no reusable native checkpoint")
    groups, per_file, grouped = [], [], []
    for native_group in raw.get("groups", []):
        if not isinstance(native_group, dict) or not isinstance(native_group.get("files"), list):
            raise ValueError("context native groups are invalid")
        files = native_group["files"]
        if any(not isinstance(p, str) or p not in selected for p in files):
            raise ValueError("context native group has an out-of-scope path")
        grouped.extend(files)
        pending = [p for p in files if p in failed]
        per_file.extend([p] for p in pending)
        if pending:
            middle = (len(pending) + 1) // 2
            groups.extend(p for p in (pending[:middle], pending[middle:]) if p)
    if (len(grouped) != len(set(grouped)) or set(grouped) != set(selected)
        or plan.get("groups") not in (groups, per_file)):
        raise ValueError("context groups must refine only the original failed native groups")
    return {"raw": raw, "selected": selected, "reused": [*done.values(), *reused.values()],
            "groups": plan["groups"], "paths": paths}


def prepare(*, source_request: Path, source_result: Path, raw_review: Path, session_record: Path,
            candidate_message_id: str, source_d1_incomplete_event_id: str, output: Path,
            per_file: bool = False) -> dict[str, Any]:
    request, raw = read(source_request), read(raw_review)
    failed = identities(raw.get("manifest", {}).get("coverage", {}).get("failed"))
    groups = []
    for group in raw.get("groups", []):
        pending = [p for p in group["files"] if p in failed]
        middle = (len(pending) + 1) // 2
        groups.extend(([p] for p in pending) if per_file else
                      (p for p in (pending[:middle], pending[middle:]) if p))
    plan = {"schema_version": SCHEMA, "run_id": request["run_id"], "cell_id": request["cell_id"],
            "candidate_message_id": candidate_message_id, "source_d1_incomplete_event_id": source_d1_incomplete_event_id,
            "sources": {k: {"path": str(p.resolve()), "sha256": digest(p)} for k, p in
                        {"request": source_request, "result": source_result, "raw_review": raw_review,
                         "session_record": session_record}.items()}, "groups": groups}
    basis = validate(plan, request, plan)
    output.parent.mkdir(parents=True, exist_ok=True)
    Attempt(output.parent).write_json_once(output.name, plan)
    return {"status": "CONTEXT_REVIEW_PREPARED", "path": str(output.resolve()), "sha256": digest(output),
            "selected": len(basis["selected"]), "reused": len(basis["reused"]), "groups": groups}


def validate_segment(basis: Mapping[str, Any], value: Mapping[str, Any], scoped_paths: list[str]) -> None:
    raw = read(Path(str(value.get("artifacts", {}).get("raw_review", ""))))
    manifest = raw.get("manifest", {})
    coverage = manifest.get("coverage", {})
    selected = identities(coverage.get("selected"))
    done = identities(coverage.get("completed"))
    reused = identities(coverage.get("reused", []))
    failed = identities(coverage.get("failed", []))
    parent = basis["raw"]["manifest"]
    if (manifest.get("schema_version") != "ocr.run-manifest/v1" or manifest.get("operation") != "review"
        or manifest.get("run_id") != raw.get("session_id")
        or raw.get("session_id") != value["review"]["session_id"] or raw.get("session_id") == basis["raw"]["session_id"]
        or manifest.get("parent_run_id") is not None or reused or coverage.get("waived")
        or manifest.get("input") != parent["input"] or manifest.get("repository") != parent.get("repository")
        or selected != {p: basis["selected"][p] for p in scoped_paths}
        or set(done) & set(failed) or {**done, **failed} != selected
        or any(manifest.get("execution", {}).get(k) != parent["execution"].get(k)
               for k in ("provider", "model"))
        or not isinstance(raw.get("comments"), list)
        or any(not isinstance(x, dict) or str(x.get("severity", "")).upper()
               not in {"INFO", "LOW", "MEDIUM", "HIGH", "BLOCKER", "CRITICAL"} for x in raw["comments"])
        or (value["verdict"] == "PASS" and any(str(x.get("severity", "")).upper()
            in {"MEDIUM", "HIGH", "BLOCKER", "CRITICAL"} for x in raw["comments"]))
        or (value["verdict"] != "INCOMPLETE" and
            (failed or done != selected or manifest.get("terminal_state") != "complete" or raw.get("status") != "complete"))):
        raise ValueError("context segment changed the candidate, coverage or native identity")
