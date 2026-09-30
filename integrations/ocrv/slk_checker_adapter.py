#!/usr/bin/env python3
"""SLK-owned OCRV D1 adapter with exact background and preview preflight."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path
from typing import Any


REQUEST_SCHEMA = "slk.ocrv-d1-request/v2"
RESULT_SCHEMA = "slk.ocrv-d1-result/v1"
PREFLIGHT_SCHEMA = "slk.ocrv-d1-preflight/v1"
EXPECTED_PROVIDER = "dashscope-tokenplan"
EXPECTED_MODEL = "qwen3.8-max"
REQUEST_FIELDS = {
    "schema_version", "run_id", "cell_id", "repository", "candidate", "cell_goal",
    "d1_criteria", "evidence_files", "review_scope", "capacity",
}
SCOPE_FIELDS = {"include_paths", "exclude_paths", "criterion_ids", "scope_sha256"}
CAPACITY_FIELDS = {
    "max_background_characters", "max_background_bytes", "max_changed_lines",
    "max_segment_paths", "max_tokens", "max_tokens_budget", "timeout_minutes",
}
ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
SHA_PATTERN = re.compile(r"^[0-9a-fA-F]{40,64}$")


class RequestError(ValueError):
    pass


def _canonical_sha(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RequestError(f"invalid request JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise RequestError("request must be a JSON object")
    return value


def _write_json_atomic(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _nonempty(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RequestError(f"{label} must be a non-empty string")
    return value.strip()


def _identifier(value: Any, label: str) -> str:
    text = _nonempty(value, label)
    if not ID_PATTERN.fullmatch(text):
        raise RequestError(f"{label} has an unsupported identifier shape")
    return text


def _string_array(value: Any, label: str, *, allow_empty: bool = False) -> list[str]:
    if not isinstance(value, list) or (not value and not allow_empty) or not all(
        isinstance(item, str) and item.strip() for item in value
    ):
        raise RequestError(f"{label} must be a {'possibly empty ' if allow_empty else ''}string array")
    return [item.strip().replace("\\", "/") for item in value]


def _validate_candidate(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or "kind" not in value:
        raise RequestError("candidate must be an object with kind")
    kind = value["kind"]
    if kind == "commit":
        if set(value) != {"kind", "commit"} or not SHA_PATTERN.fullmatch(str(value.get("commit", ""))):
            raise RequestError("commit candidate requires only an exact 40-64 hex commit")
    elif kind == "range":
        if set(value) != {"kind", "from", "to"}:
            raise RequestError("range candidate requires only kind, from, and to")
        _nonempty(value["from"], "candidate.from")
        _nonempty(value["to"], "candidate.to")
    elif kind == "workspace":
        if set(value) != {"kind"}:
            raise RequestError("workspace candidate accepts no additional fields")
    else:
        raise RequestError("candidate.kind must be commit, range, or workspace")
    return dict(value)


def _compact_evidence(path: Path) -> dict[str, Any]:
    item: dict[str, Any] = {
        "path": str(path), "sha256": _sha256(path), "bytes": path.stat().st_size,
    }
    try:
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        item["summary"] = {"format": "opaque"}
        return item
    summary: dict[str, Any] = {"format": "json"}
    if isinstance(raw, dict):
        if isinstance(raw.get("status"), str):
            summary["status"] = raw["status"]
        if isinstance(raw.get("candidate"), dict):
            summary["candidate"] = {
                key: value for key, value in raw["candidate"].items()
                if key in {"kind", "commit", "from", "to", "sha256"} and isinstance(value, str)
            }
        next_payload = raw.get("next_payload")
        if isinstance(next_payload, dict) and isinstance(next_payload.get("changed_paths"), list):
            summary["changed_paths"] = [
                value for value in next_payload["changed_paths"][:1000]
                if isinstance(value, str) and value
            ]
        for key in ("base_commit", "head_commit", "candidate_commit", "test_status"):
            if isinstance(raw.get(key), str):
                summary[key] = raw[key]
    item["summary"] = summary
    return item


def _validate_request(value: dict[str, Any]) -> dict[str, Any]:
    if set(value) != REQUEST_FIELDS or value.get("schema_version") != REQUEST_SCHEMA:
        raise RequestError("request must use the exact v2 field set")
    repository = Path(_nonempty(value["repository"], "repository")).resolve()
    if not repository.is_dir():
        raise RequestError("repository must be an existing directory")
    scope = value["review_scope"]
    if not isinstance(scope, dict) or set(scope) != SCOPE_FIELDS:
        raise RequestError("review_scope must use the exact field set")
    include = _string_array(scope["include_paths"], "include_paths", allow_empty=True)
    exclude = _string_array(scope["exclude_paths"], "exclude_paths", allow_empty=True)
    criterion_ids = _string_array(scope["criterion_ids"], "criterion_ids")
    if len(include) != len(set(include)) or len(exclude) != len(set(exclude)) or set(include) & set(exclude):
        raise RequestError("review scope paths must be unique and disjoint")
    scope_body = {"include_paths": include, "exclude_paths": exclude, "criterion_ids": criterion_ids}
    if scope["scope_sha256"] != _canonical_sha(scope_body):
        raise RequestError("review scope hash mismatch")
    capacity = value["capacity"]
    if not isinstance(capacity, dict) or set(capacity) != CAPACITY_FIELDS or not all(
        isinstance(capacity[name], int) and not isinstance(capacity[name], bool) and capacity[name] > 0
        for name in CAPACITY_FIELDS
    ):
        raise RequestError("capacity must use the exact positive-integer field set")
    criteria = _string_array(value["d1_criteria"], "d1_criteria")
    if len(criteria) != len(criterion_ids):
        raise RequestError("criterion_ids must bind every supplied D1 criterion")
    evidence_paths = value["evidence_files"]
    if not isinstance(evidence_paths, list):
        raise RequestError("evidence_files must be an array")
    evidence: list[dict[str, Any]] = []
    for raw_path in evidence_paths:
        path = Path(_nonempty(raw_path, "evidence file")).resolve()
        if not path.is_file():
            raise RequestError(f"evidence file does not exist: {path}")
        evidence.append(_compact_evidence(path))
    return {
        "schema_version": REQUEST_SCHEMA,
        "run_id": _identifier(value["run_id"], "run_id"),
        "cell_id": _identifier(value["cell_id"], "cell_id"),
        "repository": str(repository),
        "candidate": _validate_candidate(value["candidate"]),
        "cell_goal": _nonempty(value["cell_goal"], "cell_goal"),
        "d1_criteria": criteria,
        "evidence": evidence,
        "review_scope": {**scope_body, "scope_sha256": scope["scope_sha256"]},
        "capacity": dict(capacity),
    }


def _discover_capabilities(request: dict[str, Any], artifact_root: Path) -> dict[str, Any]:
    available = ["ocrv-preview"]
    selected: list[str] = []
    invocations: list[dict[str, Any]] = []
    probe = shutil.which("probe") or shutil.which("probe.cmd")
    rtk_candidates = [
        shutil.which("rtk"),
        str(Path.home() / ".codex" / "tools" / "rtk" / "rtk.exe"),
    ]
    rtk = next((item for item in rtk_candidates if item and Path(item).is_file()), None)
    if probe:
        available.append("probe-cli")
    if rtk:
        available.append("rtk")
    include = request["review_scope"]["include_paths"]
    if probe and len(include) >= 2:
        command = [probe, "--max-tokens", "300", "--timeout", "10", "symbols", *include, "--format", "json"]
        completed = subprocess.run(
            command, cwd=request["repository"], stdin=subprocess.DEVNULL, capture_output=True,
            text=True, encoding="utf-8", errors="replace", check=False, **_no_window_kwargs(),
        )
        stdout_path = artifact_root / "probe.stdout.txt"
        stderr_path = artifact_root / "probe.stderr.txt"
        stdout_path.write_text(completed.stdout, encoding="utf-8", newline="\n")
        stderr_path.write_text(completed.stderr, encoding="utf-8", newline="\n")
        selected.append("probe-cli")
        invocations.append({
            "tool": "probe-cli", "exit_code": completed.returncode,
            "stdout_sha256": _sha256(stdout_path), "stderr_sha256": _sha256(stderr_path),
        })
    return {"available": available, "selected": selected, "invocations": invocations}


def _background(request: dict[str, Any], capabilities: dict[str, Any]) -> str:
    lines = [
        "# SLK D1 Review Input", "", f"- Run: `{request['run_id']}`",
        f"- CELL: `{request['cell_id']}`",
        f"- Candidate: `{json.dumps(request['candidate'], ensure_ascii=False, sort_keys=True)}`",
        f"- Scope: `{request['review_scope']['scope_sha256']}`", "", "## CELL Goal", "",
        request["cell_goal"], "", "## D1 Criteria", "",
    ]
    lines.extend(f"{index}. {criterion}" for index, criterion in enumerate(request["d1_criteria"], 1))
    lines.extend(["", "## Evidence Index", ""])
    scoped_paths = set(request["review_scope"]["include_paths"])
    if request["evidence"]:
        for item in request["evidence"]:
            summary = dict(item["summary"])
            changed_paths = summary.get("changed_paths")
            if scoped_paths and isinstance(changed_paths, list):
                summary["changed_paths"] = [path for path in changed_paths if path in scoped_paths]
            lines.append(f"- `{item['path']}` — sha256 `{item['sha256']}`, {item['bytes']} bytes")
            lines.append("  " + json.dumps(summary, ensure_ascii=False, sort_keys=True))
    else:
        lines.append("- None supplied; do not invent runtime evidence.")
    for invocation in capabilities["invocations"]:
        lines.append(f"- Optional {invocation['tool']} digest: `{invocation['stdout_sha256']}`")
    lines.extend(["", "Review independently against every D1 criterion; Worker D0 conclusions are excluded."])
    return "\n".join(lines) + "\n"


def _no_window_kwargs() -> dict[str, Any]:
    if os.name != "nt":
        return {}
    startup = subprocess.STARTUPINFO()
    startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startup.wShowWindow = subprocess.SW_HIDE
    return {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0), "startupinfo": startup}


def _ocr_command() -> list[str]:
    override = os.environ.get("OCRV_SLK_COMMAND_JSON")
    if override:
        value = json.loads(override)
        if not isinstance(value, list) or not value or not all(isinstance(item, str) and item for item in value):
            raise RequestError("OCRV_SLK_COMMAND_JSON must be a non-empty string array")
        return value
    script = Path(__file__).resolve().with_name("ocr-slk.ps1")
    return ["powershell.exe", "-NoLogo", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script)]


def _candidate_args(candidate: dict[str, Any]) -> list[str]:
    if candidate["kind"] == "commit":
        return ["--commit", candidate["commit"]]
    if candidate["kind"] == "range":
        return ["--from", candidate["from"], "--to", candidate["to"]]
    return []


def _review_args(request: dict[str, Any], background_path: Path, output_path: Path) -> list[str]:
    capacity = request["capacity"]
    command = _ocr_command() + [
        "review", "--repo", request["repository"], "--background-file", str(background_path),
        "--audience", "agent", "--format", "json", "--output", str(output_path),
        "--concurrency", "1", "--effort", "medium", "--provider", EXPECTED_PROVIDER,
        "--model", EXPECTED_MODEL, "--max-tokens", str(capacity["max_tokens"]),
        "--max-tokens-budget", str(capacity["max_tokens_budget"]),
        "--timeout", str(capacity["timeout_minutes"]),
    ] + _candidate_args(request["candidate"])
    if request["review_scope"]["exclude_paths"]:
        command.extend(["--exclude", ",".join(request["review_scope"]["exclude_paths"])])
    return command


def _artifact_root(request: dict[str, Any]) -> tuple[str, Path]:
    invocation = str(uuid.uuid4())
    runtime = Path(os.environ.get("OCRV_SLK_RUNTIME_ROOT", r"F:\OCRV\slk-checker")).resolve()
    root = runtime / request["run_id"] / request["cell_id"] / invocation
    root.mkdir(parents=True, exist_ok=True)
    return invocation, root


def preflight(request_path: Path, output_path: Path) -> int:
    request = _validate_request(_read_json(request_path))
    _invocation, root = _artifact_root(request)
    capabilities = _discover_capabilities(request, root)
    background = _background(request, capabilities)
    background_path = root / "d1-background.md"
    background_path.write_text(background, encoding="utf-8", newline="\n")
    encoded = background.encode("utf-8")
    preview_path = root / "ocrv-preview.json"
    stdout_path = root / "ocrv-preview.stdout.txt"
    stderr_path = root / "ocrv-preview.stderr.txt"
    within_capacity = (
        len(background) <= request["capacity"]["max_background_characters"]
        and len(encoded) <= request["capacity"]["max_background_bytes"]
    )
    preview: dict[str, Any] = {}
    exit_code = 0
    stdout = ""
    stderr = ""
    command = _review_args(request, background_path, preview_path) + ["--preview"]
    completed = subprocess.run(
        command, cwd=request["repository"], stdin=subprocess.DEVNULL, capture_output=True,
        text=True, encoding="utf-8", errors="replace", check=False, **_no_window_kwargs(),
    )
    exit_code, stdout, stderr = completed.returncode, completed.stdout, completed.stderr
    source = preview_path.read_text(encoding="utf-8-sig") if preview_path.is_file() else stdout
    try:
        parsed = json.loads(source)
        preview = parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        preview = {}
    stdout_path.write_text(stdout, encoding="utf-8", newline="\n")
    stderr_path.write_text(stderr, encoding="utf-8", newline="\n")
    files = preview.get("files") if isinstance(preview.get("files"), list) else []
    inventory = [item for item in files if isinstance(item, dict)]
    selected = [str(item["path"]).replace("\\", "/") for item in inventory if item.get("will_review") is True]
    status = "READY" if within_capacity and exit_code == 0 and isinstance(preview.get("files"), list) else "INCOMPLETE"
    result = {
        "schema_version": PREFLIGHT_SCHEMA, "status": status,
        "run_id": request["run_id"], "cell_id": request["cell_id"],
        "request_sha256": _sha256(request_path),
        "background": {
            "characters": len(background), "bytes": len(encoded),
            "evidence_bytes": sum(item["bytes"] for item in request["evidence"]),
            "sha256": _sha256(background_path),
        },
        "preview": {
            "exit_code": exit_code, "selected_paths": selected, "inventory": inventory,
            "stdout_sha256": _sha256(stdout_path), "stderr_sha256": _sha256(stderr_path),
        },
        "scope": request["review_scope"], "capabilities": capabilities,
    }
    _write_json_atomic(output_path.resolve(), result)
    return 0 if status == "READY" else 3


def _coverage_complete(review: dict[str, Any]) -> bool:
    manifest = review.get("manifest")
    coverage = manifest.get("coverage") if isinstance(manifest, dict) else None
    if not isinstance(manifest, dict) or manifest.get("terminal_state") != "complete" or not isinstance(coverage, dict):
        return False
    selected, completed = coverage.get("selected"), coverage.get("completed")
    if not isinstance(selected, list) or not selected or not isinstance(completed, list):
        return False
    selected_ids = {item.get("item_id") for item in selected if isinstance(item, dict)}
    completed_ids = {item.get("item_id") for item in completed if isinstance(item, dict)}
    return None not in selected_ids and selected_ids == completed_ids and not coverage.get("failed") and not coverage.get("waived")


def _classify(review: dict[str, Any] | None, exit_code: int) -> tuple[str, list[str]]:
    reasons: list[str] = []
    if exit_code != 0:
        reasons.append(f"OCR_EXIT_{exit_code}")
    if not isinstance(review, dict):
        return "INCOMPLETE", reasons + ["OCR_RESULT_MISSING_OR_INVALID"]
    llm = review.get("llm") if isinstance(review.get("llm"), dict) else {}
    if review.get("status") != "complete":
        reasons.append("OCR_STATUS_NOT_COMPLETE")
    if llm.get("provider") != EXPECTED_PROVIDER or llm.get("model") != EXPECTED_MODEL:
        reasons.append("OCR_MODEL_IDENTITY_MISMATCH")
    if not _coverage_complete(review):
        reasons.append("OCR_COVERAGE_INCOMPLETE")
    tools = review.get("tool_calls") if isinstance(review.get("tool_calls"), dict) else {}
    if tools.get("failure", 0) != 0:
        reasons.append("OCR_TOOL_FAILURE")
    if reasons:
        return "INCOMPLETE", reasons
    comments = review.get("comments")
    if not isinstance(comments, list):
        return "INCOMPLETE", ["OCR_COMMENTS_INVALID"]
    return ("FAIL", ["OCR_FINDINGS_PRESENT"]) if comments else ("PASS", ["OCR_COMPLETE_ZERO_FINDINGS"])


def run(request_path: Path, output_path: Path) -> int:
    request = _validate_request(_read_json(request_path))
    invocation, root = _artifact_root(request)
    capabilities = _discover_capabilities(request, root)
    background_path = root / "d1-background.md"
    background_path.write_text(_background(request, capabilities), encoding="utf-8", newline="\n")
    raw_path = root / "ocrv-review.json"
    stdout_path, stderr_path = root / "ocrv.stdout.txt", root / "ocrv.stderr.txt"
    completed = subprocess.run(
        _review_args(request, background_path, raw_path), cwd=request["repository"],
        stdin=subprocess.DEVNULL, capture_output=True, text=True, encoding="utf-8",
        errors="replace", check=False, **_no_window_kwargs(),
    )
    stdout_path.write_text(completed.stdout, encoding="utf-8", newline="\n")
    stderr_path.write_text(completed.stderr, encoding="utf-8", newline="\n")
    review: dict[str, Any] | None = None
    if raw_path.is_file():
        try:
            parsed = json.loads(raw_path.read_text(encoding="utf-8-sig"))
            review = parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            pass
    verdict, reasons = _classify(review, completed.returncode)
    llm = review.get("llm", {}) if isinstance(review, dict) else {}
    result = {
        "schema_version": RESULT_SCHEMA, "run_id": request["run_id"], "cell_id": request["cell_id"],
        "review_invocation_id": invocation, "verdict": verdict, "reason_codes": reasons,
        "findings": review.get("comments", []) if isinstance(review, dict) else [],
        "review": {
            "status": review.get("status") if isinstance(review, dict) else None,
            "provider": llm.get("provider") if isinstance(llm, dict) else None,
            "model": llm.get("model") if isinstance(llm, dict) else None,
            "session_id": review.get("session_id") if isinstance(review, dict) else None,
            "exit_code": completed.returncode,
        },
        "evidence": request["evidence"], "request_sha256": _sha256(request_path),
        "artifacts": {
            "background": str(background_path), "raw_review": str(raw_path),
            "stdout": str(stdout_path), "stderr": str(stderr_path),
        },
    }
    _write_json_atomic(output_path.resolve(), result)
    return {"PASS": 0, "FAIL": 2, "INCOMPLETE": 3}[verdict]


def main() -> int:
    parser = argparse.ArgumentParser(description="Run one SLK OCRV D1 operation.")
    parser.add_argument("--preflight", action="store_true")
    parser.add_argument("--request", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        return (preflight if args.preflight else run)(args.request.resolve(), args.output.resolve())
    except (RequestError, OSError, json.JSONDecodeError) as exc:
        print(f"SLK_OCRV_REQUEST_INVALID: {exc}", file=sys.stderr)
        return 4


if __name__ == "__main__":
    raise SystemExit(main())
