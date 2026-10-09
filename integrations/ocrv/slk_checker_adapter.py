#!/usr/bin/env python3
"""SLK-owned OCRV D1 adapter with exact background and preview preflight."""

from __future__ import annotations

import argparse
import ctypes
import errno
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from datetime import datetime, timezone
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
            stream.flush()
            os.fsync(stream.fileno())
        for attempt in range(3):
            try:
                os.replace(temporary, path)
                break
            except OSError as exc:
                if exc.errno not in {errno.EBUSY, errno.EPERM} or attempt == 2:
                    raise
                time.sleep(0.01 * (attempt + 1))
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
        if isinstance(raw.get("candidate"), dict):
            summary["candidate"] = {
                key: value for key, value in raw["candidate"].items()
                if key in {"kind", "commit", "from", "to", "sha256"} and isinstance(value, str)
            }
        next_payload = raw.get("next_payload")
        if isinstance(next_payload, dict) and isinstance(next_payload.get("changed_paths"), list):
            all_paths = [value for value in next_payload["changed_paths"]
                         if isinstance(value, str) and value]
            shown = all_paths[:1000]
            summary["changed_paths"] = shown
            summary["changed_paths_summary"] = {
                "total": len(all_paths),
                "shown": len(shown),
                "omitted": len(all_paths) - len(shown),
                "source": str(path.resolve()),
            }
        for key in ("base_commit", "head_commit", "candidate_commit"):
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
    if not isinstance(capacity, dict) or set(capacity) != CAPACITY_FIELDS:
        raise RequestError("capacity must use the exact field set")
    positive = CAPACITY_FIELDS - {"max_tokens_budget", "timeout_minutes"}
    if not all(
        isinstance(capacity[name], int) and not isinstance(capacity[name], bool) and capacity[name] > 0
        for name in positive
    ) or not all(
        isinstance(capacity[name], int) and not isinstance(capacity[name], bool) and capacity[name] >= 0
        for name in ("max_tokens_budget", "timeout_minutes")
    ):
        raise RequestError("capacity values are invalid")
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
    lines.extend(["", "## Evidence Index — locators, not Worker acceptance conclusions", ""])
    scoped_paths = set(request["review_scope"]["include_paths"])
    if request["evidence"]:
        for item in request["evidence"]:
            summary = {key: value for key, value in item["summary"].items() if key in {
                "format", "candidate", "changed_paths", "changed_paths_summary",
                "base_commit", "head_commit", "candidate_commit"}}
            changed_paths = summary.get("changed_paths")
            if scoped_paths and isinstance(changed_paths, list):
                summary["changed_paths"] = [path for path in changed_paths if path in scoped_paths]
            lines.append(f"- `{item['path']}` — sha256 `{item['sha256']}`, {item['bytes']} bytes")
            lines.append("  " + json.dumps(summary, ensure_ascii=False, sort_keys=True))
    else:
        lines.append("- None supplied; do not invent runtime evidence.")
    for invocation in capabilities["invocations"]:
        lines.append(f"- Optional {invocation['tool']} digest: `{invocation['stdout_sha256']}`")
    lines.extend(["", "Inspect the candidate against every D1 criterion and form your independent preliminary judgment",
        "before reading Worker D0 originals; then read the indexed originals and reconcile any contradictions",
        "before your final D1 decision. The initial index contains locators only, not Worker self-evaluation.",
        "Your D1 decision concerns the entire frozen candidate and every CELL criterion,",
        "not the current file or native group. Native grouping and concurrency=1 do not prove",
        "whole-candidate review. Use existing file_find/file_read_diff and indexed originals",
        "to inspect related changes across groups before deciding. Do not submit one decision per group",
        "or repeat a previously submitted whole-CELL decision. If you cannot establish all CELL goals,",
        "do not claim whole-CELL PASS; disclose the unverified scope and retain all existing output.",
        "Only you, the original OCRV Checker, own D1. State your actual decision and limitations.",
        "Counts, severity, coverage and exit codes do not decide for you; host text never authorizes D1.",
        "Use slk_checker_decide(verdict) for your explicit final D1 action when that bound MCP",
        "tool is available. If unavailable or failed, disclose that fact; never claim a state",
        "write succeeded. The report remains deliverable independently of this action."])
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
        "--audience", "human", "--format", "json", "--output", str(output_path),
        "--concurrency", "1", "--effort", "medium", "--provider", EXPECTED_PROVIDER,
        "--model", EXPECTED_MODEL, "--max-tokens", str(capacity["max_tokens"]),
        "--max-tokens-budget", str(capacity["max_tokens_budget"]),
        "--timeout", str(capacity["timeout_minutes"]), "--max-tools", "0",
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


def _process_creation_time(pid: int) -> str:
    if os.name != "nt":
        stat = Path(f"/proc/{pid}/stat")
        fields = stat.read_text(encoding="ascii").split()
        return f"proc-start:{fields[21]}"
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.restype = ctypes.c_void_p
    handle = kernel32.OpenProcess(0x1000, False, pid)
    if not handle:
        raise RequestError("native OCRV process is not queryable")
    try:
        created = ctypes.c_ulonglong()
        exited = ctypes.c_ulonglong()
        kernel = ctypes.c_ulonglong()
        user = ctypes.c_ulonglong()
        if not kernel32.GetProcessTimes(
            handle,
            ctypes.byref(created),
            ctypes.byref(exited),
            ctypes.byref(kernel),
            ctypes.byref(user),
        ):
            raise RequestError("native OCRV process creation time is unavailable")
        return f"win-filetime:{created.value}"
    finally:
        kernel32.CloseHandle(handle)


def _native_context() -> tuple[Path, dict[str, str]] | None:
    receipt = os.environ.get("SLK_NATIVE_START_RECEIPT")
    raw = os.environ.get("SLK_NATIVE_START_CONTEXT")
    if not receipt or not raw:
        return None
    try:
        context = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RequestError("SLK native start context is invalid") from exc
    required = {
        "adapter",
        "run_id",
        "cell_id",
        "message_id",
        "request_sha256",
        "native_request_sha256",
    }
    if not isinstance(context, dict) or set(context) != required or not all(
        isinstance(context[name], str) and context[name] for name in required
    ):
        raise RequestError("SLK native start context is not closed")
    path = Path(receipt).resolve()
    if not path.is_absolute():
        raise RequestError("SLK native start receipt must be absolute")
    return path, context


def _publish_native_start(
    receipt_path: Path,
    context: dict[str, str],
    invocation: str,
    pid: int,
) -> tuple[Path, list[dict[str, Any]]]:
    value = {
        "schema_version": "slk.native-start/v2",
        "status": "STARTED",
        "adapter": context["adapter"],
        "run_id": context["run_id"],
        "cell_id": context["cell_id"],
        "message_id": context["message_id"],
        "request_sha256": context["request_sha256"],
        "native_request_sha256": context["native_request_sha256"],
        "observed_at": datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z"),
        "process": {"pid": pid, "creation_time": _process_creation_time(pid)},
        "native_task": {"kind": "ocrv-review", "id": invocation, "status": "RUNNING"},
    }
    _write_json_atomic(receipt_path, value)
    activity_path = receipt_path.with_name("native-activity.json")
    event_tail = [{
        "kind": "OCRV_PROCESS_STARTED",
        "sequence": 0,
        "observed_at": value["observed_at"],
        "detail_sha256": hashlib.sha256(invocation.encode("utf-8")).hexdigest(),
    }]
    _write_json_atomic(
        activity_path,
        {
            "schema_version": "slk.native-task-activity/v1",
            "adapter": context["adapter"],
            "run_id": context["run_id"],
            "cell_id": context["cell_id"],
            "message_id": context["message_id"],
            "native_task_id": invocation,
            "status": "RUNNING",
            "sequence": 0,
            "observed_at": value["observed_at"],
            "last_event": {
                "kind": "OCRV_PROCESS_STARTED", "sequence": 0, "tail": event_tail,
            },
            "waiting_on": "OCRV_REVIEW",
        },
    )
    return activity_path, event_tail


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
    status = "READY" if exit_code == 0 and isinstance(preview.get("files"), list) else "INCOMPLETE"
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





def _normalized_findings(review: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Keep formal provider findings while excluding non-evidence reasoning payloads."""

    comments = review.get("comments") if isinstance(review, dict) else None
    if not isinstance(comments, list):
        return []
    excluded = {"thinking", "reasoning", "analysis"}
    return [
        {key: value for key, value in comment.items() if key not in excluded}
        for comment in comments
        if isinstance(comment, dict)
    ]


def run(
    request_path: Path, output_path: Path, *, invocation_override: str | None = None,
    background_override: Path | None = None, resume_session: str | None = None,
    result_request_path: Path | None = None,
) -> int:
    request = _validate_request(_read_json(request_path))
    invocation, root = (invocation_override, output_path.resolve().parent) if invocation_override else _artifact_root(request)
    background_path = background_override or root / "d1-background.md"
    if background_override is None:
        background_path.write_text(_background(request, _discover_capabilities(request, root)), encoding="utf-8", newline="\n")
    raw_path = root / "ocrv-review.json"
    stdout_path, stderr_path = root / "ocrv.stdout.txt", root / "ocrv.stderr.txt"
    command = _review_args(request, background_path, raw_path) + (["--resume", resume_session] if resume_session else [])
    process = subprocess.Popen(
        command, cwd=request["repository"],
        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding="utf-8", errors="replace", **_no_window_kwargs(),
    )
    native = _native_context()
    activity_path: Path | None = None
    activity_tail: list[dict[str, Any]] = []
    if native is not None:
        activity_path, activity_tail = _publish_native_start(
            native[0], native[1], invocation, process.pid
        )
    stdout_lines: list[str] = []
    stderr_lines: list[str] = []

    def drain(stream: Any, destination: list[str], kind: str) -> None:
        sequence = 0
        for line in iter(stream.readline, ""):
            destination.append(line)
            if kind == "OCRV_PROGRESS" and activity_path is not None:
                sequence += 1
                observed_at = datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")
                detail_sha256 = hashlib.sha256(line.encode("utf-8")).hexdigest()
                activity_tail.append({
                    "kind": kind, "sequence": sequence, "observed_at": observed_at,
                    "detail_sha256": detail_sha256,
                })
                del activity_tail[:-12]
                _write_json_atomic(
                    activity_path,
                    {
                        "schema_version": "slk.native-task-activity/v1",
                        "adapter": native[1]["adapter"] if native is not None else "ocrv-checker",
                        "run_id": native[1]["run_id"] if native is not None else request["run_id"],
                        "cell_id": native[1]["cell_id"] if native is not None else request["cell_id"],
                        "message_id": native[1]["message_id"] if native is not None else "unknown",
                        "native_task_id": invocation,
                        "status": "RUNNING",
                        "sequence": sequence,
                        "observed_at": observed_at,
                        "last_event": {
                            "kind": kind,
                            "sequence": sequence,
                            "summary_sha256": detail_sha256,
                            "tail": list(activity_tail),
                        },
                        "waiting_on": "OCRV_REVIEW",
                    },
                )
        stream.close()

    stdout_thread = threading.Thread(target=drain, args=(process.stdout, stdout_lines, "OCRV_STDOUT"))
    stderr_thread = threading.Thread(target=drain, args=(process.stderr, stderr_lines, "OCRV_PROGRESS"))
    stdout_thread.start()
    stderr_thread.start()
    returncode = process.wait()
    stdout_thread.join()
    stderr_thread.join()
    stdout = "".join(stdout_lines)
    stderr = "".join(stderr_lines)
    stdout_path.write_text(stdout, encoding="utf-8", newline="\n")
    stderr_path.write_text(stderr, encoding="utf-8", newline="\n")
    if activity_path is not None:
        exit_sequence = len(stderr_lines) + 1
        exit_observed_at = datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")
        activity_tail.append({
            "kind": "OCRV_PROCESS_EXITED", "sequence": exit_sequence,
            "observed_at": exit_observed_at,
            "detail_sha256": hashlib.sha256(str(returncode).encode("utf-8")).hexdigest(),
        })
        del activity_tail[:-12]
        _write_json_atomic(
            activity_path,
            {
                "schema_version": "slk.native-task-activity/v1",
                "adapter": native[1]["adapter"] if native is not None else "ocrv-checker",
                "run_id": native[1]["run_id"] if native is not None else request["run_id"],
                "cell_id": native[1]["cell_id"] if native is not None else request["cell_id"],
                "message_id": native[1]["message_id"] if native is not None else "unknown",
                "native_task_id": invocation,
                "status": "COMPLETED" if returncode == 0 else "FAILED",
                "sequence": exit_sequence,
                "observed_at": exit_observed_at,
                "last_event": {
                    "kind": "OCRV_PROCESS_EXITED",
                    "sequence": exit_sequence,
                    "exit_code": returncode,
                    "tail": list(activity_tail),
                },
                "waiting_on": None,
            },
        )
    review: dict[str, Any] | None = None
    if raw_path.is_file():
        try:
            parsed = json.loads(raw_path.read_text(encoding="utf-8-sig"))
            review = parsed if isinstance(parsed, dict) else None
        except (UnicodeDecodeError, json.JSONDecodeError):
            pass
    # Only an explicit native Checker verdict may be copied; findings and exit are facts.
    verdict = review.get("verdict") if isinstance(review, dict) else None
    reasons = review.get("reason_codes", []) if isinstance(review, dict) else []
    llm = review.get("llm", {}) if isinstance(review, dict) else {}
    result = {
        "schema_version": RESULT_SCHEMA, "run_id": request["run_id"], "cell_id": request["cell_id"],
        "review_invocation_id": invocation, "verdict": verdict, "reason_codes": reasons,
        "verdict_source": "CHECKER_EXPLICIT" if verdict is not None else None,
        "findings": _normalized_findings(review),
        "review": {
            "status": review.get("status") if isinstance(review, dict) else None,
            "provider": llm.get("provider") if isinstance(llm, dict) else None,
            "model": llm.get("model") if isinstance(llm, dict) else None,
            "session_id": review.get("session_id") if isinstance(review, dict) else None,
            "exit_code": returncode,
        },
        "evidence": request["evidence"], "request_sha256": _sha256(result_request_path or request_path),
        "artifacts": {
            "background": str(background_path), "raw_review": str(raw_path),
            "stdout": str(stdout_path), "stderr": str(stderr_path),
        },
    }
    _write_json_atomic(output_path.resolve(), result)
    return returncode


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
