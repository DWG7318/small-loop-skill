#!/usr/bin/env python3
"""SLK-owned OCRV D1 adapter with exact background and preview preflight."""

from __future__ import annotations

import argparse
import ctypes
from ctypes import wintypes
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
LEGACY_CAPACITY_FIELDS = {
    "max_background_characters", "max_background_bytes", "max_changed_lines",
    "max_segment_paths",
}
CAPACITY_FIELDS = {"max_tokens", "max_tokens_budget", "timeout_minutes"}
ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
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
            summary["changed_paths"] = all_paths
            summary["changed_paths_summary"] = {
                "total": len(all_paths),
                "shown": len(all_paths),
                "omitted": 0,
                "source": str(path.resolve()),
            }
        # Only existing explicit public D0 locators grant admission. Never scan
        # prose, tool output, private reasoning or arbitrary JSON path fields.
        declared = []
        for owner in (raw, next_payload):
            d0 = owner.get("d0") if isinstance(owner, dict) else None
            refs = d0.get("evidence_files") if isinstance(d0, dict) else None
            if isinstance(refs, list):
                declared.extend(ref for ref in refs if isinstance(ref, str) and ref.strip())
        if declared:
            summary["declared_evidence_files"] = declared
        for key in ("base_commit", "head_commit", "candidate_commit"):
            if isinstance(raw.get(key), str):
                summary[key] = raw[key]
    item["summary"] = summary
    return item


def _private_evidence_reason(path: Path) -> str | None:
    name = path.name.lower()
    if name in {"native.stdout.txt", "native.stderr.txt", "ocrv.stdout.txt", "ocrv.stderr.txt",
                "thinking.txt", "reasoning.txt"}:
        return "PRIVATE_DIAGNOSTIC"
    # Native OCRV/Codex JSONL and DSH session stores contain private messages,
    # reasoning and tool payloads. A D0 locator (even frozen) cannot make them
    # public evidence. Check the resolved source before any content read/hash;
    # ordinary public D0 logs outside these native storage shapes stay uncapped.
    parents = {part.lower() for part in path.parts[:-1]}
    if (parents & {"sessions", "archived_sessions"}
        and (path.suffix.lower() == ".jsonl"
             or (name.startswith("session-") and path.suffix.lower() == ".json"))):
        return "PRIVATE_DIAGNOSTIC"
    if (name in {".env", "auth.json", "credentials.json", "credentials", "id_rsa", "id_ed25519"}
        or name.startswith(".env.") or path.suffix.lower() in {".dpapi", ".key", ".pem"}
        or any(part.lower() in {"credentials", ".ssh", ".secrets"} for part in path.parts)):
        return "PRIVATE_CREDENTIAL"
    return None


def _validate_request(value: dict[str, Any]) -> dict[str, Any]:
    if (set(value) - {"management_context", "evidence_refs"} != REQUEST_FIELDS
        or value.get("schema_version") != REQUEST_SCHEMA):
        raise RequestError("request must use the v2 field set with optional management_context and evidence_refs")
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
    if not isinstance(capacity, dict) or set(capacity) not in (CAPACITY_FIELDS, CAPACITY_FIELDS | LEGACY_CAPACITY_FIELDS):
        raise RequestError("capacity must use the exact field set")
    positive = {"max_tokens"}
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
    frozen_refs = value.get("evidence_refs", [])
    if not isinstance(frozen_refs, list):
        raise RequestError("evidence_refs must be an array")
    frozen_paths = set()
    for ref in frozen_refs:
        if (not isinstance(ref, dict) or set(ref) - {"bytes"} != {"path", "sha256"}
            or not isinstance(ref["path"], str) or not Path(ref["path"]).is_absolute()
            or not isinstance(ref["sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", ref["sha256"])
            or ("bytes" in ref and (type(ref["bytes"]) is not int or ref["bytes"] < 0))):
            raise RequestError("frozen evidence requires an exact absolute path and sha256")
        path = Path(ref["path"]).resolve()
        if path in frozen_paths:
            raise RequestError("duplicate frozen evidence path")
        frozen_paths.add(path)
    evidence: list[dict[str, Any]] = []
    evidence_gaps = []
    frozen_by_path = {Path(ref["path"]).resolve(): ref for ref in frozen_refs}
    pending = [(raw, None) for raw in evidence_paths] + [(ref["path"], None) for ref in frozen_refs]
    seen: set[Path] = set()
    for raw_path, declared_by in pending:
        path = Path(_nonempty(raw_path, "evidence file"))
        if not path.is_absolute():
            evidence_gaps.append({"path": str(path), "reason": "NOT_ABSOLUTE", "declared_by": declared_by})
            continue
        path = path.resolve()
        if path in seen:
            continue
        seen.add(path)
        ref = frozen_by_path.get(path)
        locator = {**(ref or {}), "path": str(path)}
        if declared_by is not None:
            locator["declared_by"] = declared_by
        reason = _private_evidence_reason(path)
        if reason:
            evidence_gaps.append({**locator, "reason": reason})
            continue
        try:
            item = _compact_evidence(path)
        except OSError:
            evidence_gaps.append({**locator, "reason": "UNAVAILABLE"})
            continue
        if ref is not None and (item["sha256"] != ref["sha256"] or ("bytes" in ref and item["bytes"] != ref["bytes"])):
            evidence_gaps.append({**locator, "reason": "CHANGED", "observed_sha256": item["sha256"],
                                  "observed_bytes": item["bytes"]})
            continue
        item["availability"] = "AVAILABLE"
        if declared_by is not None:
            item["declared_by"] = declared_by
        evidence.append(item)
        pending.extend((child, str(path)) for child in item["summary"].get("declared_evidence_files", []))
    management = value.get("management_context")
    if "management_context" in value:
        fields = {"management_action", "management_summary", "management_evidence_refs"}
        if not isinstance(management, dict) or set(management) != fields:
            raise RequestError("management_context must use the exact field set")
        _nonempty(management["management_action"], "management_action")
        _nonempty(management["management_summary"], "management_summary")
        refs = management["management_evidence_refs"]
        if not isinstance(refs, list):
            raise RequestError("management_evidence_refs must be an array")
        indexed = {item["path"]: item for item in evidence}
        for ref in refs:
            if isinstance(ref, dict):
                if set(ref) != {"path", "sha256"}:
                    raise RequestError("management evidence accepts only path and sha256")
                path, expected = ref["path"], ref["sha256"]
            else:
                path, expected = ref, None
            item = indexed.get(str(Path(_nonempty(path, "management evidence")).resolve()))
            if item is None or (expected is not None and expected != item["sha256"]):
                raise RequestError("management evidence is missing or its hash changed")
    normalized = {
        "schema_version": REQUEST_SCHEMA,
        "run_id": _identifier(value["run_id"], "run_id"),
        "cell_id": _identifier(value["cell_id"], "cell_id"),
        "repository": str(repository),
        "candidate": _validate_candidate(value["candidate"]),
        "cell_goal": _nonempty(value["cell_goal"], "cell_goal"),
        "d1_criteria": criteria,
        "evidence": evidence,
        "evidence_gaps": evidence_gaps,
        "review_scope": {**scope_body, "scope_sha256": scope["scope_sha256"]},
        "capacity": dict(capacity),
    }
    if management is not None:
        normalized["management_context"] = management
    if "evidence_refs" in value:
        normalized["evidence_refs"] = [dict(ref) for ref in frozen_refs]
    return normalized


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


def _index_materials(
    request: dict[str, Any], request_path: Path, root: Path, invocation: str,
    capabilities: dict[str, Any], native_context: dict[str, str] | None = None,
) -> Path:
    """Bind full inputs without placing their content in native background."""
    identity = {
        **(native_context or {"run_id": request["run_id"], "cell_id": request["cell_id"]}),
        "native_task_id": invocation,
    }
    frozen = {"evidence_gaps": request["evidence_gaps"]}
    if "evidence_refs" in request:
        frozen["evidence_refs"] = request["evidence_refs"]
    original = _compact_evidence(request_path.resolve())
    if native_context is not None and original["sha256"] != native_context["native_request_sha256"]:
        raise RequestError("original request hash does not match native invocation")
    catalog_path = root / "material-catalog.json"
    # Catalog enumerates engineering originals only. It never hashes itself or
    # the enclosing index, and the existing request is never rewritten.
    _write_json_atomic(catalog_path, {
        **identity, "request": {"index": 0, **original},
        "evidence": [{"index": index, **item} for index, item in enumerate(request["evidence"], 2)],
        **frozen, "capabilities": capabilities,
    })
    index_path = root / "evidence-index.json"
    _write_json_atomic(index_path, {
        **identity, "evidence": [original, _compact_evidence(catalog_path), *request["evidence"]],
        **frozen,
    })
    return index_path


def _background(request: dict[str, Any]) -> str:
    lines = [
        "# SLK D1 Review Bootstrap", "",
        f"- Scope: `{request['review_scope']['scope_sha256']}`", "",
        "Before reviewing, read slk_read_evidence(0) through EOF: the complete original request.",
        "Read its candidate, entire cell_goal and every d1_criteria entry, review_scope and capacity.",
        "Preserve any Supervisor management_context as a supplement, not a replacement goal or D1 verdict.",
        "Then read slk_read_evidence(1) through EOF: the complete material catalog with numbered",
        "evidence locators, hashes, frozen references, gaps and optional capability metadata.",
        "The request contains review inputs and locators, not the separately indexed Worker D0 body.",
        "Frozen material gaps are disclosed in that catalog; unavailable originals are not acceptance evidence.",
        "If the mandatory request/catalog cannot be read completely, disclose the limitation; do not claim PASS.",
    ]
    lines.extend(["", "Inspect the candidate against every D1 criterion and form your independent preliminary judgment",
        "before reading relevant Worker D0 originals; select relevant indexed originals and reconcile contradictions",
        "before your final D1 decision. The material catalog contains locators and metadata, not Worker self-evaluation.",
        "Read runtime originals with slk_read_evidence(index, offset?, limit?) using numbers from this invocation's",
        "catalog, not prior sessions; omit limit to read through EOF, or choose offset/limit yourself. There is no tool-imposed",
        "content-length ceiling; originals are hash-checked. Git file_read in commit/range mode cannot read uncommitted runtime logs.",
        "Do not treat an index, a summary, a missing file or a truncated chunk as the full original.",
        "Your D1 decision concerns the entire frozen candidate and every CELL criterion,",
        "not the current file or native group. Native grouping and concurrency=1 do not prove",
        "whole-candidate review. Use existing file_find/file_read_diff and indexed originals",
        "to inspect related changes across groups before deciding. Do not submit one decision per group",
        "or repeat a previously submitted whole-CELL decision. If you cannot establish all CELL goals,",
        "do not claim whole-CELL PASS; disclose the unverified scope and retain all existing output.",
        "Review unchanged Shell/handshake seams required by CELL criteria; modified-file/group coverage is not whole-CELL acceptance.",
        "Only you, the original OCRV Checker, own D1. State your actual decision and limitations.",
        "Counts, severity, coverage and exit codes do not decide for you; host text never authorizes D1.",
        "File groups use task_done only; the native final whole-CELL stage follows after every group settles.",
        "In that final stage, save actual reports and evidence before using slk_checker_decide(verdict)",
        "as your last action. It persists D1 only; existing Host handoff follows natural native exit",
        "and sealed results. Do not continue reviewing after handoff.",
        "If the bound tool is unavailable or failed, disclose that fact; never claim a state",
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
    bundled = Path(__file__).resolve().parent / "bin/opencodereview.exe"
    if bundled.is_file():
        return [str(bundled)]
    return ["powershell.exe", "-NoLogo", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script)]


def _packaged_root() -> Path | None:
    root = Path(__file__).resolve().parents[2]
    return root if (root.name.lower() == "slk" and root.parent.name.lower() == "tools"
                    and (root / "scripts/local_package_metadata.py").is_file()) else None


def _child_environment() -> dict[str, str]:
    environment = os.environ.copy()
    root = _packaged_root()
    if root is not None and not shutil.which("git", path=environment.get("PATH", "")):
        git = root / "runtime/git/cmd"
        if (git / "git.exe").is_file():
            environment["PATH"] = str(git) + os.pathsep + environment.get("PATH", "")
    return environment


def _session_directory(repository: Path, environment: dict[str, str]) -> Path:
    if not os.environ.get("OCRV_SLK_COMMAND_JSON") and (Path(__file__).resolve().parent / "bin/opencodereview.exe").is_file():
        # Go's Windows os.UserHomeDir uses the actual child's USERPROFILE.
        user = environment.get("USERPROFILE")
        if not user:
            raise RequestError("native OCRV child USERPROFILE is unavailable")
        native_home = Path(user)
    else:
        # Authoritative arbitrary wrappers may select their own home internally.
        # Keep the established legacy contract rather than guessing that change.
        native_home = Path(environment.get("OCRV_RUNTIME_ROOT", r"F:\OCRV")) / "home"
    repository = repository.resolve()
    encoded = repository.drive.replace(":", "_") + str(repository)[len(repository.drive):].lstrip("/\\").replace("\\", "-").replace("/", "-")
    return native_home / ".opencodereview/sessions" / encoded


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
    packaged = _packaged_root()
    default = packaged / "data/ocrv" if packaged is not None else Path(r"F:\OCRV\slk-checker")
    runtime = Path(os.environ.get("OCRV_SLK_RUNTIME_ROOT", str(default))).resolve()
    root = runtime / request["run_id"] / request["cell_id"] / invocation
    root.mkdir(parents=True, exist_ok=True)
    return invocation, root


def _process_creation_time(pid: int) -> str:
    if os.name != "nt":
        stat = Path(f"/proc/{pid}/stat")
        fields = stat.read_text(encoding="ascii").rsplit(")", 1)[1].split()
        return f"proc-start:{fields[19]}"
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.restype = ctypes.c_void_p
    kernel32.GetProcessTimes.argtypes = [ctypes.c_void_p] + [ctypes.POINTER(ctypes.c_ulonglong)] * 4
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
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


def _process_parents() -> dict[int, int]:
    """Local OS facts, used once on explicit completion, not an activity probe."""
    if os.name != "nt":
        parents = {}
        for path in Path('/proc').glob('[0-9]*/stat'):
            try:
                parents[int(path.parent.name)] = int(path.read_text().rsplit(')', 1)[1].split()[1])
            except (OSError, ValueError, IndexError):
                pass
        return parents
    class Entry(ctypes.Structure):
        _fields_ = [("size", wintypes.DWORD), ("usage", wintypes.DWORD), ("pid", wintypes.DWORD),
            ("heap", ctypes.c_size_t), ("module", wintypes.DWORD), ("threads", wintypes.DWORD),
            ("parent", wintypes.DWORD), ("priority", wintypes.LONG), ("flags", wintypes.DWORD),
            ("name", wintypes.WCHAR * 260)]
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateToolhelp32Snapshot.restype = ctypes.c_void_p
    kernel.Process32FirstW.argtypes = kernel.Process32NextW.argtypes = [ctypes.c_void_p, ctypes.POINTER(Entry)]
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    snapshot = kernel.CreateToolhelp32Snapshot(2, 0)
    if snapshot == ctypes.c_void_p(-1).value:
        raise RequestError("native review ancestry unavailable")
    try:
        entry = Entry()
        entry.size = ctypes.sizeof(entry)
        parents = {}
        valid = kernel.Process32FirstW(snapshot, ctypes.byref(entry))
        while valid:
            parents[entry.pid] = entry.parent
            valid = kernel.Process32NextW(snapshot, ctypes.byref(entry))
        return parents
    finally:
        kernel.CloseHandle(snapshot)


def _completed_decision(path: Path, native: tuple[Path, dict], invocation: str) -> dict:
    completed = _read_json(path)
    receipt_path, context = native
    if (completed.get("schema_version") != "slk.ocrv-completion/v1"
        or any(completed.get(key) != context[key] for key in (
            "run_id", "cell_id", "message_id", "native_request_sha256"))
        or completed.get("native_task_id") != invocation
        or completed.get("native_start_sha256") != _sha256(receipt_path)):
        raise RequestError("completion receipt does not bind this native invocation")
    decision_path = receipt_path.parent / "role-host" / "checker-decision.json"
    if (Path(completed["decision_path"]).resolve() != decision_path.resolve()
        or completed["decision_sha256"] != _sha256(decision_path)):
        raise RequestError("completion decision changed")
    decision = _read_json(decision_path)
    if (decision.get("source_message_id") != context["message_id"]
        or decision.get("native_task_id") != invocation
        or decision.get("verdict") not in {"PASS", "FAIL", "INCOMPLETE"}
        or decision["verdict"] != completed["verdict"]):
        raise RequestError("completion is not this Checker's explicit decision")
    return {**completed, "message": decision.get("message")}


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
        "native_task": {"kind": "ocrv-invocation", "id": invocation, "status": "RUNNING"},
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
    invocation, root = _artifact_root(request)
    capabilities = _discover_capabilities(request, root)
    _index_materials(request, request_path, root, invocation, capabilities)
    background = _background(request)
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
    environment = _child_environment()
    completed = subprocess.run(
        command, cwd=request["repository"], stdin=subprocess.DEVNULL, capture_output=True,
        env=environment, text=True, encoding="utf-8", errors="replace", check=False, **_no_window_kwargs(),
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





def _normalized_findings(review: dict[str, Any] | None) -> list[dict[str, Any]] | None:
    """Keep formal provider findings while excluding non-evidence reasoning payloads."""

    comments = review.get("comments") if isinstance(review, dict) else None
    if not isinstance(comments, list):
        return None
    excluded = {"thinking", "reasoning", "analysis"}
    return [
        {key: value for key, value in comment.items() if key not in excluded}
        for comment in comments
        if isinstance(comment, dict)
    ]


def _normalized_retry_report(review: dict[str, Any] | None) -> dict[str, Any] | None:
    """Project the native public HTTP metadata, never bodies or SDK error text."""
    report = review.get("retry_report") if isinstance(review, dict) else None
    if (not isinstance(report, dict) or report.get("schema_version") != "ocr.llm-retry-report/v1"
        or not isinstance(report.get("requests"), list)):
        return None
    def fields(value, strings=(), integers=(), booleans=()):
        return {key: item for key, item in value.items() if
                (key in strings and isinstance(item, str)) or
                (key in integers and type(item) is int) or
                (key in booleans and type(item) is bool)}
    projected = fields(report, ("schema_version",), ("total_requests", "retried_requests",
        "total_retries", "recovered_requests", "failed_requests", "cancelled_requests"))
    projected["requests"] = []
    for request in report.get("requests", []):
        if not isinstance(request, dict) or not isinstance(request.get("attempts"), list):
            return None
        item = fields(request, ("logical_request_id", "provider", "model", "file_path", "task_type", "outcome"),
                      ("request_no",))
        item["attempts"] = [fields(attempt, ("outcome", "error_class", "failure_phase", "request_id"),
            ("attempt", "status_code", "retry_after_ms", "observed_backoff_ms", "duration_to_headers_ms"),
            ("sdk_retry_directive",)) for attempt in request.get("attempts", []) if isinstance(attempt, dict)]
        projected["requests"].append(item)
    return projected


def _transport_import_path() -> None:
    root = _packaged_root()
    if root is not None:
        package = str(root / "bin/slk-transport.pyz")
        if package not in sys.path:
            sys.path.insert(0, package)


def _verified_native_identity(receipt: Path) -> dict[str, Any]:
    """Actual public header metadata only after original marker/session binding."""
    try:
        _transport_import_path()
        from slk_transport.native_activity import validate_native_start
        from slk_transport.native_ocrv import inspect_ocrv_session
        observed = inspect_ocrv_session(receipt, validate_native_start(receipt), include_identity=True)
        return observed.get("native_identity", {}) if observed.get("error") != "OCRV_SESSION_EVENT_AFTER_END" else {}
    except (ImportError, OSError, ValueError, KeyError, TypeError):
        return {}


def _resume_preflight(native, request_path: Path, resume_session: str | None,
                      original_request_path: Path | None = None) -> dict | None:
    """Use the existing parser/Host and native binding before any paid launch."""
    if native is None:
        raise RequestError("resume/supplement requires the bound original source")
    try:
        _transport_import_path()
        from slk_transport.contracts import parse_delivery
        from slk_transport.role_host import load_role_host
        from slk_transport.native_activity import validate_native_start
        from slk_transport.native_ocrv import inspect_ocrv_session, require_stopped_ocrv
        from slk_transport.checker_escalation import _validate_explicit_decision
        from slk_transport import worker_completion as wc
        receipt, context = native
        source = receipt.parent
        endpoint = _read_json(source / "endpoint.json")
        incoming = parse_delivery(endpoint, _read_json(source / "envelope.json"))
        host = load_role_host(endpoint)
        if host is None or incoming.envelope.receiver_role != "checker":
            raise RequestError("resume requires the bound original Checker Host")
        envelope = incoming.envelope
        from slk_transport.adapters.ocrv import OcrvAdapter
        expected = OcrvAdapter()._candidate_request(envelope, OcrvAdapter._executing_capacity(endpoint["address"]))
        actual = _validate_request(_read_json(request_path))
        if (any(actual[key] != expected[key] for key in ("run_id", "cell_id", "repository", "candidate", "cell_goal", "d1_criteria", "review_scope"))
            or any(actual["capacity"][key] != expected["capacity"][key] for key in CAPACITY_FIELDS)):
            raise RequestError("resume changed the original frozen CELL/candidate scope")
        start = validate_native_start(receipt, adapter=endpoint["adapter"], run_id=envelope.run_id,
            cell_id=envelope.cell_id, message_id=envelope.message_id, request_sha256=envelope.payload_sha256,
            native_request_sha256=_sha256(original_request_path or request_path))
        if any(context[key] != start[key] for key in context):
            raise RequestError("resume context changed original identity")
        if validate_native_start(source / "started.json") != start:
            raise RequestError("resume changed the original transport/native start")
        saved = None
        decision_path = source / "role-host/checker-decision.json"
        projection = host.projection()
        if decision_path.is_file():
            decision = _read_json(decision_path)
            event_type = {"PASS": "D1_PASSED", "FAIL": "D1_FAILED", "INCOMPLETE": "D1_INCOMPLETE"}.get(decision.get("verdict"))
            events = [event for event in projection.get("events", []) if event.get("event_id") ==
                wc._stable_id(envelope.message_id, str(event_type).lower()) and event.get("event_type") == event_type
                and event.get("go_id") == envelope.go_id and event.get("cell_id") == envelope.cell_id
                and event.get("plan_revision") == host.binding["plan_revision"]]
            if len(events) != 1:
                raise RequestError("existing D1 is not authenticated in the original Host")
            _validate_explicit_decision(source, incoming.endpoint, envelope, events[0], wc._event_details(events[0]))
            saved = {**decision, "path": str(decision_path), "sha256": _sha256(decision_path)}
        elif any(event.get("event_id") == wc._stable_id(envelope.message_id, kind.lower())
                 for event in projection.get("events", []) for kind in ("D1_PASSED", "D1_FAILED", "D1_INCOMPLETE")):
            raise RequestError("recorded D1 requires its original decision source, never another model call")
        require_stopped_ocrv(receipt, start)
        observed = inspect_ocrv_session(receipt, start)
        binding = _read_json(source / "ocrv-session-binding.json")
        if (observed.get("status") != "COMPLETED" or observed.get("error")
            or resume_session != binding["session_id"]):
            raise RequestError("resume requires the exact completed original native Session")
        if saved is not None:
            return saved
        # Native resume admission requires its real closed manifest. Never invent
        # one for a killed/interrupted review just because file checkpoints exist.
        manifest = None
        with Path(binding["session_path"]).open("rb") as stream:
            for raw in stream:
                if b'"session_end"' in raw and raw.endswith(b"\n"):
                    row = json.loads(raw)
                    if row.get("type") == "session_end":
                        manifest = row.get("run_manifest")
        if not isinstance(manifest, dict):
            raise RequestError("resume requires the original closed native manifest")
        return None
    except (ImportError, OSError, ValueError, KeyError, TypeError) as exc:
        raise RequestError(f"bound original resume preflight failed: {exc}") from exc


def run(
    request_path: Path, output_path: Path, *, invocation_override: str | None = None,
    background_override: Path | None = None, resume_session: str | None = None,
    result_request_path: Path | None = None,
    resume_origin: Path | None = None,
) -> int:
    request = _validate_request(_read_json(request_path))
    environment = _child_environment()
    native = _native_context()
    if resume_session is not None or background_override is not None:
        original_native = ((resume_origin / "native-start.received.json", native[1])
                           if resume_origin is not None and native is not None else native)
        saved = _resume_preflight(original_native, request_path, resume_session, result_request_path)
        if saved is not None:
            # An authenticated D1 is already the original Checker's final act.
            # Reuse existing output only. A decision never manufactures a seal;
            # the explicit recovery entry can consume the original Host suffix.
            if output_path.is_file():
                prior = _read_json(output_path)
                if (any(prior.get(key) != request[key] for key in ("run_id", "cell_id"))
                    or prior.get("review_invocation_id") != saved["native_task_id"]
                    or prior.get("verdict") != saved["verdict"]
                    or prior.get("request_sha256") != _sha256(result_request_path or request_path)):
                    raise RequestError("existing result conflicts with authenticated original D1")
            else:
                raise RequestError("CHECKER_D1_RECORDED: original result remains unsealed; resume only its Host handoff")
            return 0
    invocation, root = (invocation_override, output_path.resolve().parent) if invocation_override else _artifact_root(request)
    background_path = background_override or root / "d1-background.md"
    if background_override is None:
        index_path = _index_materials(request, request_path, root, invocation,
            _discover_capabilities(request, root), native[1] if native is not None else None)
        background_path.write_text(_background(request), encoding="utf-8", newline="\n")
    else:
        # Legacy explicit backgrounds retain their original evidence numbering.
        # Current native resume regenerates a fresh bootstrap/catalog instead.
        index_path = root / "evidence-index.json"
        _write_json_atomic(index_path, {
            **(native[1] if native is not None else {"run_id": request["run_id"], "cell_id": request["cell_id"]}),
            "native_task_id": invocation, "evidence": request["evidence"],
            "evidence_gaps": request["evidence_gaps"],
            **({"evidence_refs": request["evidence_refs"]} if "evidence_refs" in request else {}),
        })
    source = None
    if native is not None:
        marker = f"SLK_NATIVE_INVOCATION={invocation};REQUEST_SHA256={native[1]['native_request_sha256']}"
        if background_override is not None:
            background_path = root / "d1-native-background.md"
            original_background = background_override.read_text(encoding="utf-8")
        else:
            original_background = background_path.read_text(encoding="utf-8")
        background_path.write_text(marker + "\n" + original_background, encoding="utf-8", newline="\n")
        repo = Path(request["repository"]).resolve()
        sessions = _session_directory(repo, environment)
        source = {"schema_version": "slk.ocrv-native-source/v1",
            **{key: native[1][key] for key in ("run_id", "cell_id", "message_id")},
            "invocation_id": invocation, "request_path": str(request_path.resolve()),
            "background_path": str(background_path.resolve()), "background_sha256": _sha256(background_path),
            "marker": marker, "session_directory": str(sessions.resolve()),
            "prior_sessions": sorted(path.name for path in sessions.glob("*.jsonl")),
            "resume_session_id": resume_session}
    raw_path = root / "ocrv-review.json"
    stdout_path, stderr_path = root / "ocrv.stdout.txt", root / "ocrv.stderr.txt"
    command = _review_args(request, background_path, raw_path) + (["--resume", resume_session] if resume_session else [])
    environment["SLK_CHECKER_EVIDENCE_INDEX"] = str(index_path)
    environment["SLK_CHECKER_EVIDENCE_INDEX_SHA256"] = _sha256(index_path)
    if native is not None:
        environment["SLK_CHECKER_WHOLE_CELL"] = "1"
    process = subprocess.Popen(
        command, cwd=request["repository"],
        env=environment,
        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        **_no_window_kwargs(),
    )
    activity_path: Path | None = None
    activity_tail: list[dict[str, Any]] = []
    if native is not None:
        activity_path, activity_tail = _publish_native_start(
            native[0], native[1], invocation, process.pid
        )
        _write_json_atomic(native[0].with_name("ocrv-native-source.json"),
            {**source, "native_start_sha256": _sha256(native[0])})
        if resume_origin is not None:
            # Explicit recovery is the trusted coordinator of this fresh source.
            # Publish its actual start without rewriting the original delivery.
            from slk_transport.evidence import Attempt
            Attempt(native[0].parent).write_json_once("started.json", _read_json(native[0]))
    closure_error = None
    activity_lock = threading.Lock()
    stream_errors: list[str] = []

    def drain(stream: Any, destination: Path, kind: str) -> None:
        # Original evidence is available even when exact cleanup is denied and
        # the native process remains alive. Never accumulate the full logs in RAM.
        saved = None
        stage = "open"

        def failed(operation: str, exc: Exception) -> None:
            with activity_lock:
                stream_errors.append(f"{destination.name} {operation}: {type(exc).__name__}: {exc}")

        try:
            saved = destination.open("wb")
            # A read buffer is not a total-output limit. read1 also exposes
            # flushed partial lines without waiting for a newline or native exit.
            while True:
                stage = "read"
                chunk = stream.read1(65536)
                if not chunk:
                    break
                stage = "write"
                saved.write(chunk)
                stage = "flush"
                saved.flush()
                if activity_path is None:
                    continue
                stage = "activity"
                with activity_lock:
                    sequence = activity_tail[-1]["sequence"] + 1
                    observed_at = datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")
                    detail_sha256 = hashlib.sha256(chunk).hexdigest()
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
                            **({"error": "OCRV_STREAM_FAILED"} if stream_errors else
                               {"error": "OCRV_CLEANUP_FAILED"} if closure_error is not None else {}),
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
        except Exception as exc:
            failed(stage, exc)
            if stage != "read":
                # A failed sink must not block the original native writer on a
                # full pipe. Do not retry the failed sink or invent missing bytes.
                try:
                    for _chunk in iter(lambda: stream.read1(65536), b""):
                        pass
                except Exception as exc:
                    failed("read", exc)
        finally:
            for handle, operation in ((saved, "close evidence"), (stream, "close pipe")):
                if handle is not None:
                    try:
                        handle.close()
                    except Exception as exc:
                        failed(operation, exc)

    stdout_thread = threading.Thread(target=drain, args=(process.stdout, stdout_path, "OCRV_STDOUT"))
    stderr_thread = threading.Thread(target=drain, args=(process.stderr, stderr_path, "OCRV_PROGRESS"))
    stdout_thread.start()
    stderr_thread.start()
    completed_decision = None
    completion_path = root / "review-completed.json"
    while True:
        try:
            returncode = process.wait(timeout=0.25)
            break
        except subprocess.TimeoutExpired:
            pass  # D1 persisted is not native completion; never kill pending writers.
    stdout_thread.join()
    stderr_thread.join()
    if native is not None:
        completed_decision = None
        try:
            completed_decision = _completed_decision(completion_path, native, invocation)
        except (RequestError, OSError, KeyError, TypeError, UnicodeDecodeError) as exc:
            closure_error = f"{closure_error}; {exc}" if closure_error is not None else str(exc)
    if stream_errors:
        stream_error = "OCRV_STREAM_FAILED: " + "; ".join(stream_errors)
        closure_error = f"{closure_error}; {stream_error}" if closure_error is not None else stream_error
    if activity_path is not None:
        exit_sequence = activity_tail[-1]["sequence"] + 1
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
                "status": "COMPLETED" if returncode == 0 or completed_decision is not None else "FAILED",
                **({"error": "OCRV_STREAM_FAILED"} if stream_errors else {}),
                "sequence": exit_sequence,
                "observed_at": exit_observed_at,
                "last_event": {
                    "kind": "OCRV_PROCESS_EXITED",
                    "sequence": exit_sequence,
                    "exit_code": returncode,
                    "closure_reason": "EXPLICIT_D1_COMPLETED" if completed_decision is not None else None,
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
    verdict = (completed_decision["verdict"] if completed_decision is not None else
               review.get("verdict") if native is None and isinstance(review, dict) else None)
    reasons = review.get("reason_codes", []) if isinstance(review, dict) else []
    llm = review.get("llm", {}) if isinstance(review, dict) else {}
    identity = _verified_native_identity(native[0]) if native is not None else {}
    result = {
        "schema_version": RESULT_SCHEMA, "run_id": request["run_id"], "cell_id": request["cell_id"],
        "review_invocation_id": invocation, "verdict": verdict, "reason_codes": reasons,
        "verdict_source": "CHECKER_EXPLICIT" if verdict is not None else None,
        "decision": ({"verdict": completed_decision["verdict"], "message": completed_decision.get("message"),
                      "path": completed_decision["decision_path"], "sha256": completed_decision["decision_sha256"]}
                     if completed_decision is not None else None),
        "findings": _normalized_findings(review),
        "review": {
            "status": review.get("status") if isinstance(review, dict) else None,
            "provider": identity.get("provider") if identity else llm.get("provider") if isinstance(llm, dict) else None,
            "model": identity.get("model") if identity else llm.get("model") if isinstance(llm, dict) else None,
            "session_id": identity.get("session_id") if identity else review.get("session_id") if isinstance(review, dict) else None,
            "identity_source": "VERIFIED_NATIVE_SESSION" if identity else "NATIVE_RAW_REPORT" if review else None,
            "requested": {"provider": EXPECTED_PROVIDER, "model": EXPECTED_MODEL},
            "exit_code": returncode,
            "closure_reason": "EXPLICIT_D1_COMPLETED" if completed_decision is not None else None,
            "closure_error": closure_error,
            "retry_report": _normalized_retry_report(review),
        },
        "evidence": request["evidence"], "evidence_gaps": request["evidence_gaps"],
        "request_sha256": _sha256(result_request_path or request_path),
        "artifacts": {
            "background": str(background_path), "raw_review": str(raw_path),
            "stdout": str(stdout_path), "stderr": str(stderr_path),
        },
    }
    _write_json_atomic(output_path.resolve(), result)
    if stream_errors:
        return returncode or 1
    return 0 if completed_decision is not None else returncode


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
