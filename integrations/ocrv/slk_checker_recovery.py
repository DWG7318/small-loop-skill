#!/usr/bin/env python3
"""Narrow OCRV launcher for one authenticated SLK Worker-completion recovery."""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
import slk_checker_adapter as checker_adapter


def windows_no_window_kwargs() -> dict[str, object]:
    if os.name != "nt":
        return {}
    startup = subprocess.STARTUPINFO()
    startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startup.wShowWindow = subprocess.SW_HIDE
    return {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0), "startupinfo": startup}


def _transport_runtime_path(command: list[str]) -> Path:
    """Resolve only the two managed transport command forms to their real zipapp."""

    if len(command) == 2:
        python_path = Path(command[0]).resolve()
        zipapp = Path(command[1]).resolve()
        if (
            python_path == Path(sys.executable).resolve()
            and zipapp.name.lower() == "slk-transport.pyz"
            and zipapp.is_file()
        ):
            return zipapp
    elif len(command) == 1:
        launcher = Path(command[0]).resolve()
        zipapp = launcher.with_name("slk-transport.pyz")
        try:
            text = launcher.read_text(encoding="utf-8-sig").replace("\r\n", "\n")
        except (OSError, UnicodeError):
            text = ""
        if (
            launcher.name.lower() == "slk-transport.cmd"
            and launcher.is_file()
            and zipapp.is_file()
            and text
            == '@echo off\npython "%~dp0slk-transport.pyz" %*\nexit /b %ERRORLEVEL%\n'
        ):
            return zipapp
    raise ValueError("managed SLK transport runtime is unavailable or changed")


def _creation_time(pid: int) -> str:
    if os.name != "nt":
        fields = Path(f"/proc/{pid}/stat").read_text(encoding="ascii").split()
        return f"proc-start:{fields[21]}"
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.restype = ctypes.c_void_p
    handle = kernel32.OpenProcess(0x1000, False, pid)
    if not handle:
        raise OSError("recovery process identity unavailable")
    try:
        created = ctypes.c_ulonglong()
        exited = ctypes.c_ulonglong()
        kernel = ctypes.c_ulonglong()
        user = ctypes.c_ulonglong()
        if not kernel32.GetProcessTimes(
            handle, ctypes.byref(created), ctypes.byref(exited), ctypes.byref(kernel), ctypes.byref(user)
        ):
            raise OSError("recovery process creation time unavailable")
        return f"win-filetime:{created.value}"
    finally:
        kernel32.CloseHandle(handle)


def _publish_start(native_request_sha256: str, invocation_id: str) -> None:
    path_raw = os.environ.get("SLK_NATIVE_START_RECEIPT")
    context_raw = os.environ.get("SLK_NATIVE_START_CONTEXT")
    if not path_raw or not context_raw:
        return
    context = json.loads(context_raw)
    if context.get("native_request_sha256") != native_request_sha256:
        raise ValueError("native start request hash mismatch")
    value = {
        "schema_version": "slk.native-start/v2",
        "status": "STARTED",
        "adapter": context["adapter"],
        "run_id": context["run_id"],
        "cell_id": context["cell_id"],
        "message_id": context["message_id"],
        "request_sha256": context["request_sha256"],
        "native_request_sha256": native_request_sha256,
        "observed_at": datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z"),
        "process": {"pid": os.getpid(), "creation_time": _creation_time(os.getpid())},
        "native_task": {
            "kind": "ocrv-recovery-wrapper",
            "id": invocation_id,
            "status": "RUNNING",
        },
    }
    destination = Path(path_raw).resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(value, stream, ensure_ascii=False, sort_keys=True, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _sha256(path: Path) -> str: return hashlib.sha256(path.read_bytes()).hexdigest()


def _request_transport_command(request: dict[str, object], *, fresh: bool) -> list[str]:
    source = request
    if fresh:
        for path_key, digest_key in (
            ("fresh_request_path", "fresh_request_sha256"),
            ("source_request_path", "source_request_sha256"),
        ):
            if isinstance(source.get("transport_command"), list):
                break
            raw_path = source.get(path_key)
            expected = source.get(digest_key)
            if raw_path is None and expected is None:
                continue
            path = Path(raw_path) if isinstance(raw_path, str) else Path()
            if (
                not path.is_absolute() or not path.is_file() or not isinstance(expected, str)
                or re.fullmatch(r"[0-9a-f]{64}", expected) is None or _sha256(path) != expected
            ):
                raise ValueError("fresh-review source request is unavailable or changed")
            try:
                source = json.loads(path.read_text(encoding="utf-8-sig"))
            except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                raise ValueError("fresh-review source request is unreadable") from exc
            if not isinstance(source, dict):
                raise ValueError("fresh-review source request is not an object")
    command = source.get("transport_command")
    if not isinstance(command, list) or not command or not all(
        isinstance(item, str) and item for item in command
    ):
        raise ValueError("transport command is invalid")
    return command


def _run_ocrv_json(arguments: list[str]) -> object:
    completed = subprocess.run(
        checker_adapter._ocr_command() + arguments,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        **windows_no_window_kwargs(),
    )
    if completed.returncode:
        raise ValueError(f"OCRV read-only precheck failed ({completed.returncode})")
    return json.loads(completed.stdout)


def _ocrv_version() -> str:
    completed = subprocess.run(
        checker_adapter._ocr_command() + ["--version"],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        **windows_no_window_kwargs(),
    )
    match = re.search(r"(?m)^open-code-review (v\d+\.\d+\.\d+)\b", completed.stdout)
    if completed.returncode or match is None:
        raise ValueError("OCRV version precheck failed")
    return match.group(1)


def _session_resume_mode(request: dict[str, object], session: dict[str, object]) -> tuple[str, dict[str, object]]:
    repository = str(request["candidate_repository"])
    rows = _run_ocrv_json(["session", "list", "--json", "--repo", repository])
    if not isinstance(rows, list):
        raise ValueError("OCRV session list is invalid")
    matches = [row for row in rows if isinstance(row, dict) and row.get("session_id") == session["session_id"]]
    session_facts = ("diff_commit", "model", "review_mode", "start_time", "aborted", "selected_files", "completed_files")
    if (
        len(matches) != 1
        or str(matches[0].get("repo_dir", "")).replace("\\", "/") != str(session["repo_dir"]).replace("\\", "/")
        or any(matches[0].get(key) != session[key] for key in session_facts)
    ):
        raise ValueError("OCRV session is no longer the exact aborted session")
    detail = _run_ocrv_json([
        "session", "show", "--json", "--repo", repository, str(session["session_id"]),
    ])
    if not isinstance(detail, dict) or set(detail) != {"summary", "items"}:
        raise ValueError("OCRV session detail is invalid")
    summary, items = detail["summary"], detail["items"]
    if not isinstance(summary, dict) or (items is not None and not isinstance(items, list)):
        raise ValueError("OCRV session detail is invalid")
    if summary.get("session_id") != session["session_id"]:
        raise ValueError("OCRV session detail identifies a different session")
    manifest = summary.get("run_manifest")
    mode = "RESUME_SESSION" if isinstance(manifest, dict) and isinstance(items, list) and bool(items) else "FRESH_REVIEW"
    return mode, detail


def _resume_incomplete(request: dict[str, object], request_path: Path, command: list[str]) -> int:
    if 'partial_review' in request:
        return _resume_partial(request, request_path, command)
    checker, session = request["checker_endpoint"], request["ocrv_session"]
    if not isinstance(checker, dict) or not isinstance(session, dict):
        raise ValueError("resume identity is invalid")
    if (
        os.environ.get("SLK_OCRV_RECOVERY_ROLE_INSTANCE_ID") != request["checker_role_instance_id"]
        or os.environ.get("SLK_OCRV_RECOVERY_ENDPOINT_VERSION") != str(request["checker_endpoint_version"])
    ):
        raise ValueError("resume is outside the exact Checker host")
    original = Path(str(request["native_attempt_path"])).resolve() / "ocrv-request.json"
    background = Path(str(request["background_path"])).resolve()
    mode, session_detail = _session_resume_mode(request, session)
    invocation_id = str(session["session_id"]) if mode == "RESUME_SESSION" else str(uuid.uuid4())
    root = Path(str(request["recovery_root"])).resolve(); root.mkdir(parents=True, exist_ok=True)
    detail_path = root / "session-show.json"
    detail_path.write_text(json.dumps(session_detail, sort_keys=True) + "\n", encoding="utf-8")
    attempt = root / "native-attempt"
    attempt.mkdir()
    resume = {
        "schema_version": "slk.ocrv-d1-resume-request/v1", "run_id": request["run_id"],
        "cell_id": request["cell_id"], "message_id": request["candidate_message_id"],
        "strategy": mode, "review_invocation_id": invocation_id,
        "payload_sha256": request["payload_sha256"], "original_request_path": str(original),
        "original_request_sha256": _sha256(original), "background_path": str(background),
        "background_sha256": _sha256(background), "session_show_sha256": _sha256(detail_path),
        "session": {key: session[key] for key in (
            "session_id", "repo_dir", "diff_commit", "model", "review_mode", "start_time",
            "aborted", "selected_files", "completed_files",
        )},
    }
    resume_path = attempt / "ocrv-resume-request.json"
    resume_path.write_text(json.dumps(resume, sort_keys=True) + "\n", encoding="utf-8")
    os.environ["SLK_NATIVE_START_RECEIPT"] = str(attempt / "native-start.received.json")
    os.environ["SLK_NATIVE_START_CONTEXT"] = json.dumps({"adapter": "ocrv-checker", "run_id": request["run_id"],
        "cell_id": request["cell_id"], "message_id": request["candidate_message_id"],
        "request_sha256": request["payload_sha256"], "native_request_sha256": _sha256(resume_path)}, sort_keys=True, separators=(",", ":"))
    with (root / "resume-consumed.json").open("x", encoding="ascii") as stream:
        stream.write(_sha256(request_path) + "\n")
    code = checker_adapter.run(original, attempt / "ocrv-result.json", invocation_override=invocation_id,
        background_override=background,
        resume_session=str(session["session_id"]) if mode == "RESUME_SESSION" else None,
        result_request_path=resume_path)
    result = json.loads((attempt / "ocrv-result.json").read_text(encoding="utf-8"))
    review_session_id = result.get("review", {}).get("session_id")
    if (
        result.get("review_invocation_id") != invocation_id
        or not isinstance(review_session_id, str)
        or (mode == "RESUME_SESSION" and review_session_id != session["session_id"])
        or (mode == "FRESH_REVIEW" and review_session_id == session["session_id"])
    ):
        raise ValueError("OCRV recovery identity mismatch")
    started = json.loads((attempt / "native-start.received.json").read_text(encoding="utf-8")); (attempt / "started.json").write_text(json.dumps(started, sort_keys=True) + "\n", encoding="utf-8")
    if started.get("native_task", {}).get("id") != invocation_id:
        raise ValueError("OCRV recovery start identity mismatch")
    review = result["review"]
    terminal = {
        "schema_version": "slk.transport-result/v1", "message_id": request["candidate_message_id"],
        "run_id": request["run_id"], "adapter": "ocrv-checker", "status": "completed",
        "native_identity": {"run_id": request["run_id"], "cell_id": request["cell_id"],
            "review_invocation_id": invocation_id, "session_id": review["session_id"],
            "provider": review["provider"], "model": review["model"], "verdict": result["verdict"],
            "exit_code": code, "review_segment_count": 0},
        "error_code": None, "evidence": ["started.json", "ocrv-resume-request.json", "ocrv-result.json"],
    }
    (attempt / "completed.json").write_text(json.dumps(terminal, sort_keys=True) + "\n", encoding="utf-8")
    raw = attempt / "ocrv-review.json"
    committed = {key: value for key, value in request.items() if key not in {
        "schema_version", "background_path", "ocrv_session", "recovery_root",
    }}
    committed.update({
        "schema_version": "slk.ocrv-committed-terminal-request/v1", "raw_review_path": str(raw),
        "result_path": str(root / "committed-terminal-result.json"),
        "immutable_sha256": {name: request["immutable_sha256"][name] for name in (
            "endpoint.json", "envelope.json", "started.json", "ocrv-request.json",
        )},
        "recovery_terminal": {
            "native_attempt_path": str(attempt), "started_sha256": _sha256(attempt / "started.json"),
            "completed_sha256": _sha256(attempt / "completed.json"),
            "ocrv_result_sha256": _sha256(attempt / "ocrv-result.json"),
            "resume_request_sha256": _sha256(resume_path), "raw_review_sha256": _sha256(raw),
        },
    })
    committed_path = root / "committed-terminal.json"
    committed_path.write_text(json.dumps(committed, sort_keys=True) + "\n", encoding="utf-8")
    committed_sha256 = _sha256(committed_path)
    completed = subprocess.run(command + ["checker-record-committed-terminal", "--request", str(committed_path),
        "--sha256", committed_sha256], stdin=subprocess.DEVNULL, capture_output=True, check=False,
        env=os.environ.copy(), **windows_no_window_kwargs())
    if completed.returncode == 0:
        outer = json.loads(completed.stdout)
        if outer.get("request_sha256") != committed_sha256:
            raise ValueError("committed terminal result is not bound to its request")
        outer["request_sha256"] = _sha256(request_path)
        encoded = (json.dumps(outer, sort_keys=True) + "\n").encode("utf-8")
        Path(str(request["result_path"])).write_bytes(encoded)
        sys.stdout.buffer.write(encoded)
    else:
        sys.stdout.buffer.write(completed.stdout)
    sys.stderr.buffer.write(completed.stderr)
    return completed.returncode


def _terminal_budget_post_d1_suffix(
    request: dict[str, object], validated: dict[str, object], result: dict[str, object],
    attempt: Path, root: Path, command: list[str],
) -> dict[str, object]:
    """Route a corrected PASS/FAIL through the existing sealed Checker suffix."""

    from slk_transport import checker_completion as passed
    from slk_transport import checker_escalation as failed
    from slk_transport import worker_completion as wc
    from slk_transport.role_host import normalized_checker_findings

    correction = validated.get("d1_correction")
    correction_id = correction.get("correction_id") if isinstance(correction, dict) else None
    if not isinstance(correction_id, str) or not correction_id:
        raise ValueError("validated D1 correction identity is unavailable")
    event_id = wc._stable_id(
        str(request["candidate_message_id"]), "d1-budget-" + correction_id,
    )
    projection = dict(
        wc._default_load_current_projection(str(request["run_id"]), list(request["state_command"]))
    )
    snapshot = projection.get("runtime_snapshot")
    events = projection.get("events")
    matches = [
        event for event in events or []
        if isinstance(event, dict) and event.get("event_id") == event_id
    ]
    if (
        not isinstance(snapshot, dict)
        or snapshot.get("token_holder_role_instance_id") != request["checker_role_instance_id"]
        or not isinstance(events, list)
        or len(matches) != 1
        or matches[0].get("event_type")
        != {"PASS": "D1_PASSED", "FAIL": "D1_FAILED"}.get(result.get("verdict"))
        or matches[0].get("corrects_event_id") != request["d1_incomplete_event_id"]
    ):
        raise ValueError("corrected D1 is not the exact current Checker terminal")
    details = matches[0].get("details")
    if not isinstance(details, dict):
        serialized = matches[0].get("details_json")
        details = json.loads(serialized) if isinstance(serialized, str) else None
    if (
        not isinstance(details, dict)
        or details.get("verdict") != result.get("verdict")
        or details.get("candidate_message_id") != request["candidate_message_id"]
    ):
        raise ValueError("corrected D1 details do not bind the resumed candidate")

    projection_path = wc._write_or_reuse_stable_request(
        root / "post-d1-projection.json", projection
    )
    binding = validated["role_host_binding"]
    if not isinstance(binding, dict):
        raise ValueError("frozen RoleHost binding is unavailable")
    cells = passed._ordered_cells(projection)
    bound_cells = binding.get("cells")
    if (
        not isinstance(bound_cells, list)
        or [cell.get("cell_id") for cell in bound_cells]
        != [cell.get("cell_id") for cell in cells]
    ):
        raise ValueError("current required CELL set differs from the frozen RoleHost binding")
    common = {
        "method_version": request["method_version"],
        "run_id": request["run_id"],
        "go_id": request["go_id"],
        "cell_id": request["cell_id"],
        "attempt": request["attempt"],
        "plan_revision": request["plan_revision"],
        "runtime_revision": snapshot["runtime_revision"],
        "token_sequence": snapshot["token_sequence"],
        "checker_role_instance_id": request["checker_role_instance_id"],
        "runtime_projection_path": str(projection_path),
        "checker_credential_path": request["checker_credential_path"],
        "state_command": request["state_command"],
        "transport_command": request["transport_command"],
        "occurred_at": matches[0].get("occurred_at"),
    }
    roles = binding["roles"]
    verdict = result["verdict"]
    if verdict == "FAIL":
        current = next(
            cell for cell in bound_cells if cell.get("cell_id") == request["cell_id"]
        )
        payload = current.get("payload")
        if not isinstance(payload, dict):
            raise ValueError("frozen current CELL payload is unavailable")
        suffix_request = {
            **common,
            "schema_version": failed.REQUEST_SCHEMA,
            "post_d1_invocation_id": wc._stable_id(event_id, "normal-fail"),
            "d1_failure_event_id": event_id,
            "native_attempt_path": str(attempt),
            "supervisor_endpoint_path": roles["supervisor"]["endpoint_path"],
            "escalation_attempt_root": str(root),
            "rework_round": 1 + sum(
                event.get("event_type") == "REWORK_REQUESTED"
                and event.get("cell_id") == request["cell_id"]
                for event in events
            ),
            "cell_goal": payload["task"],
            "acceptance_criteria": payload["d1_criteria"],
            "findings": normalized_checker_findings(result.get("findings", [])),
            "reproduction_steps": [
                "Read the original Checker findings and cited evidence; do not infer a reproduction."
            ],
            "expected_result": "Satisfy the unchanged CELL acceptance criteria.",
            "evidence_refs": [str(attempt / "ocrv-result.json")],
        }
        mode = "--slk-post-d1"
        output = root / ".checker-post-d1" / suffix_request["post_d1_invocation_id"] / "prepared-result.json"
        accepted_statuses = {"DESKTOP_BRIDGE_REQUIRED", "CHECKER_ESCALATION_COMMITTED"}
    else:
        ids = [str(cell["cell_id"]) for cell in cells]
        index = ids.index(str(request["cell_id"]))
        final = index == len(ids) - 1
        target_role = "supervisor" if final else "worker"
        payload = (
            {
                "d1_event_id": event_id,
                "required_cell_ids": ids,
                "accepted_cell_ids": ids,
                "final_candidate_message_id": request["candidate_message_id"],
                "d2_criteria": binding["d2_criteria"],
                "evidence_refs": [str(attempt / "ocrv-result.json")],
            }
            if final
            else bound_cells[index + 1]["payload"]
        )
        suffix_request = {
            **common,
            "schema_version": passed.REQUEST_SCHEMA,
            "completion_invocation_id": wc._stable_id(event_id, "normal-pass"),
            "d1_event_id": event_id,
            "target_cell_id": str(request["cell_id"]) if final else ids[index + 1],
            "route": "D2_READY" if final else "NEXT_CELL",
            "target_endpoint_path": roles[target_role]["endpoint_path"],
            "handoff_attempt_root": str(root),
            "payload": payload,
        }
        mode = "--slk-complete-d1"
        output = root / ".checker-completion" / suffix_request["completion_invocation_id"] / "result.json"
        accepted_statuses = {"CHECKER_COMPLETION_COMMITTED", "DESKTOP_BRIDGE_REQUIRED"}

    suffix_path = wc._write_or_reuse_stable_request(root / "post-d1-request.json", suffix_request)
    checker_command = request["checker_endpoint"].get("address", {}).get("command")
    if (
        not isinstance(checker_command, list)
        or not checker_command
        or not all(isinstance(item, str) and item for item in checker_command)
    ):
        raise ValueError("sealed Checker host command is unavailable")
    environment = os.environ.copy()
    environment.pop("SLK_ROLE_CREDENTIAL", None)
    environment.pop("SLK_OVERWATCHER_CREDENTIAL", None)
    completed = subprocess.run(
        [*checker_command, mode, "--request", str(suffix_path), "--output", str(output)],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        check=False,
        env=environment,
        **windows_no_window_kwargs(),
    )
    if completed.returncode != 0:
        sys.stdout.buffer.write(completed.stdout)
        sys.stderr.buffer.write(completed.stderr)
        raise ValueError("sealed Checker post-D1 suffix failed")
    suffix_result = json.loads(completed.stdout)
    if not isinstance(suffix_result, dict) or suffix_result.get("status") not in accepted_statuses:
        raise ValueError("sealed Checker post-D1 suffix returned an invalid result")
    return {
        "corrected_d1_event_id": event_id,
        "suffix_mode": mode,
        "suffix_request_path": str(suffix_path),
        "suffix_result_path": str(output),
        "suffix_status": suffix_result["status"],
    }


def _authenticate_terminal_budget(
    source: dict[str, object], validated: dict[str, object], invocation_id: str,
) -> None:
    from slk_transport import worker_completion as wc

    role_id = source["checker_role_instance_id"]
    if (
        os.environ.get("SLK_OCRV_RECOVERY_ROLE_INSTANCE_ID") != role_id
        or os.environ.get("SLK_OCRV_RECOVERY_ENDPOINT_VERSION")
        != str(source["checker_endpoint_version"])
        or os.environ.get("SLK_OCRV_RECOVERY_INVOCATION_ID") != invocation_id
    ):
        raise ValueError("terminal-budget review is outside the original sealed Checker")
    authentication = wc._default_checker_authenticate(
        source["run_id"], role_id, Path(source["checker_credential_path"]), source["state_command"]
    )
    if (
        authentication.get("status") != "authenticated"
        or authentication.get("role") != "checker"
        or authentication.get("role_instance_id") != role_id
    ):
        raise ValueError("terminal-budget Checker authentication failed before model start")
    if authentication.get("runtime_revision") != source["runtime_revision"]:
        frozen = validated.get("frozen_projection") or validated["source_validated"]["frozen_projection"]
        wc._rebind_overwatcher_only_committed_boundary(
            source, frozen,
            wc._default_load_current_projection(source["run_id"], source["state_command"]),
            authentication["runtime_revision"],
        )


def _run_terminal_budget_review(
    source: dict[str, object], validated: dict[str, object], recovery: dict[str, object],
    request_path: Path, command: list[str], *, fresh: bool, fresh_partial: bool = False,
) -> int:
    """Shared sealed OCRV execution; fresh changes only checkpoint and lineage semantics."""

    from slk_transport import worker_completion as wc
    from slk_transport.contracts import canonical_json_sha256
    from slk_transport.terminal_budget import (
        RESULT_SCHEMA, read_session_records, validate_resumed_child,
    )
    from slk_transport.terminal_budget_fresh import (
        MODEL, PROVIDER, RESULT_SCHEMA as FRESH_RESULT_SCHEMA, validate_fresh_child,
    )
    from slk_transport.terminal_budget_fresh_partial import (
        RESULT_SCHEMA as FRESH_PARTIAL_RESULT_SCHEMA, validate_fresh_partial_child,
    )

    session = source["ocrv_session"]
    root = Path(recovery["recovery_root"]).resolve()
    attempt = root / "native-attempt"
    attempt.mkdir()
    original = json.loads(
        (Path(source["native_attempt_path"]).resolve() / "ocrv-request.json").read_text(
            encoding="utf-8-sig"
        )
    )
    original["capacity"] = {**original["capacity"], **source["capacity_revision"]["new"]}
    capacity_path = attempt / "ocrv-capacity-request.json"
    capacity_path.write_text(json.dumps(original, sort_keys=True) + "\n", encoding="utf-8")
    os.environ["SLK_NATIVE_START_RECEIPT"] = str(attempt / "native-start.received.json")
    os.environ["SLK_NATIVE_START_CONTEXT"] = json.dumps(
        {
            "adapter": "ocrv-checker", "run_id": source["run_id"], "cell_id": source["cell_id"],
            "message_id": source["candidate_message_id"], "request_sha256": source["payload_sha256"],
            "native_request_sha256": _sha256(capacity_path),
        },
        sort_keys=True, separators=(",", ":"),
    )
    invocation_id = str(uuid.uuid4())
    code = checker_adapter.run(
        capacity_path, attempt / "ocrv-result.json", invocation_override=invocation_id,
        background_override=Path(source["background_path"]).resolve(),
        resume_session=None if fresh else str(session["session_id"]),
        result_request_path=capacity_path,
    )
    result = json.loads((attempt / "ocrv-result.json").read_text(encoding="utf-8"))
    child_session_id = result.get("review", {}).get("session_id")
    if (
        result.get("review_invocation_id") != invocation_id
        or not isinstance(child_session_id, str) or not child_session_id
        or child_session_id == session["session_id"]
        or result.get("review", {}).get("provider") != PROVIDER
        or result.get("review", {}).get("model") != MODEL
        or result.get("verdict") not in {"PASS", "FAIL", "INCOMPLETE"}
    ):
        raise ValueError("terminal-budget OCRV result changed the model or Session identity")
    raw_path = attempt / "ocrv-review.json"
    raw_review = json.loads(raw_path.read_text(encoding="utf-8-sig"))
    child_detail = _run_ocrv_json([
        "session", "show", "--json", "--repo", str(source["candidate_repository"]), child_session_id,
    ])
    child_summary = child_detail.get("summary") if isinstance(child_detail, dict) else None
    if (
        not isinstance(child_detail, dict) or set(child_detail) != {"summary", "items"}
        or not isinstance(child_summary, dict)
        or child_summary.get("session_id") != child_session_id
        or child_summary.get("run_manifest") != raw_review.get("manifest")
    ):
        raise ValueError("terminal-budget child Session does not match the native result")
    child_path = Path(str(child_summary.get("file_path", ""))).resolve()
    expected_child = Path(str(source["session_record_path"])).resolve().parent / (
        child_session_id + ".jsonl"
    )
    if child_path != expected_child or not child_path.is_file():
        raise ValueError("terminal-budget child Session escaped the frozen OCRV store")
    native_session_path = attempt / "native-session.jsonl"
    native_session_path.write_bytes(child_path.read_bytes())
    records = read_session_records(native_session_path)
    parent_raw = json.loads(Path(str(source["raw_review_path"])).read_text(encoding="utf-8-sig"))
    validation = {
        "target_ocrv_version": validated["target_ocrv_version"],
        "target_rule_config_sha256": validated["target_rule_config_sha256"],
        "target_runtime_config_sha256": validated["target_runtime_config_sha256"],
    }
    if fresh:
        validate_fresh_child(parent_raw, raw_review, child_records=records, **validation)
        lineage = {
            "schema_version": "slk.ocrv-terminal-budget-fresh-compatibility-lineage/v1",
            "strategy": recovery["strategy"],
            "source_request_path": recovery["source_request_path"],
            "source_request_sha256": recovery["source_request_sha256"],
            "source_rejection_sha256": recovery["source_rejection_sha256"],
            "compatibility_request_path": str(request_path.resolve()),
            "compatibility_request_sha256": _sha256(request_path),
            "parent_session_id": session["session_id"], "child_session_id": child_session_id,
            "review_invocation_id": invocation_id, "candidate_commit": source["candidate_commit"],
            "candidate_message_id": source["candidate_message_id"],
            "d1_started_event_id": source["d1_started_event_id"],
            "d1_incomplete_event_id": source["d1_incomplete_event_id"],
            "authorization_sha256": canonical_json_sha256(recovery["owner_authorization"]),
            "native_session_sha256": _sha256(native_session_path), "checkpoint_reuse": False,
        }
        lineage_name = "compatibility-lineage.json"
    else:
        native_lineage = [row for row in records if row.get("type") == "resume_lineage"]
        ends = [row for row in records if row.get("type") == "session_end"]
        if len(native_lineage) != 1 or len(ends) != 1 or ends[0].get(
            "run_manifest"
        ) != raw_review.get("manifest"):
            raise ValueError("terminal-budget child Session lineage or terminal manifest is incomplete")
        validate_resumed_child(parent_raw, raw_review, native_lineage[0], **validation)
        if fresh_partial:
            validate_fresh_partial_child(parent_raw, raw_review)
        lineage = {
            "schema_version": "slk.ocrv-terminal-budget-resume-lineage/v1",
            "source_request_path": str(request_path.resolve()),
            "source_request_sha256": _sha256(request_path),
            "original_native_request_sha256": source["immutable_sha256"]["ocrv-request.json"],
            "original_terminal_sha256": source["immutable_sha256"]["completed.json"],
            "original_result_sha256": source["immutable_sha256"]["ocrv-result.json"],
            "original_raw_review_sha256": source["immutable_sha256"]["raw_review"],
            "session_show_sha256": _sha256(root / "session-show.json"),
            "parent_session_id": session["session_id"], "child_session_id": child_session_id,
            "review_invocation_id": invocation_id,
            "native_session_sha256": _sha256(native_session_path),
            "d1_started_event_id": source["d1_started_event_id"],
            "d1_incomplete_event_id": source["d1_incomplete_event_id"],
            "capacity_revision_sha256": canonical_json_sha256(source["capacity_revision"]),
            "ocrv_transition_sha256": canonical_json_sha256(source["ocrv_transition"]),
            "runtime_config_binding_sha256": canonical_json_sha256(source["runtime_config_binding"]),
            "owner_authorization": source["owner_authorization"],
            "capacity_request_sha256": _sha256(capacity_path),
        }
        lineage_name = "resume-lineage.json"
    lineage_path = attempt / lineage_name
    lineage_path.write_text(json.dumps(lineage, sort_keys=True) + "\n", encoding="utf-8")
    (attempt / "started.json").write_bytes((attempt / "native-start.received.json").read_bytes())
    terminal = {
        "schema_version": "slk.transport-result/v1", "message_id": source["candidate_message_id"],
        "run_id": source["run_id"], "adapter": "ocrv-checker", "status": "completed",
        "native_identity": {
            "run_id": source["run_id"], "cell_id": source["cell_id"],
            "review_invocation_id": invocation_id, "session_id": child_session_id,
            "provider": PROVIDER, "model": MODEL, "verdict": result["verdict"],
            "exit_code": code, "review_segment_count": 0,
        },
        "error_code": None,
        "evidence": [
            "started.json", "ocrv-capacity-request.json", lineage_name,
            "native-session.jsonl", "ocrv-result.json",
        ],
    }
    (attempt / "completed.json").write_text(json.dumps(terminal, sort_keys=True) + "\n", encoding="utf-8")

    status, event_type = "CHECKER_D1_STILL_INCOMPLETE", "D1_INCOMPLETE"
    suffix = {
        "corrected_d1_event_id": None, "suffix_mode": None, "suffix_request_path": None,
        "suffix_result_path": None, "suffix_status": "NOT_APPLICABLE",
    }
    route_source = dict(source)
    route_source.update(
        recovery_invocation_id=recovery["recovery_invocation_id"],
        recovery_root=str(root), result_path=str(root / "result.json"),
    )
    if result["verdict"] != "INCOMPLETE":
        fields = (
            "method_version", "recovery_invocation_id", "run_id", "go_id", "cell_id", "attempt",
            "plan_revision", "runtime_revision", "token_sequence", "worker_role_instance_id",
            "checker_role_instance_id", "checker_endpoint_version", "checker_endpoint",
            "runtime_projection_path", "runtime_projection_sha256", "candidate_repository",
            "candidate_commit", "candidate_parent", "candidate_message_id", "payload_sha256",
            "candidate_submitted_event_id", "transport_started_event_id", "commit_request_path",
            "commit_request_sha256", "native_attempt_path", "checker_credential_path",
            "state_command", "transport_command",
        )
        recovery_terminal = {
            "native_attempt_path": str(attempt), "started_sha256": _sha256(attempt / "started.json"),
            "completed_sha256": _sha256(attempt / "completed.json"),
            "ocrv_result_sha256": _sha256(attempt / "ocrv-result.json"),
            "raw_review_sha256": _sha256(raw_path),
            "capacity_request_sha256": _sha256(capacity_path),
            "native_session_sha256": _sha256(native_session_path),
            "d1_correction": validated["d1_correction"],
        }
        if fresh:
            recovery_terminal.update(
                compatibility_request_path=str(request_path.resolve()),
                compatibility_request_sha256=_sha256(request_path),
                compatibility_lineage_sha256=_sha256(lineage_path),
            )
        elif fresh_partial:
            recovery_terminal.update(
                fresh_partial_request_path=str(request_path.resolve()),
                fresh_partial_request_sha256=_sha256(request_path),
                resume_lineage_sha256=_sha256(lineage_path),
            )
        else:
            recovery_terminal.update(
                resume_request_sha256=_sha256(lineage_path),
                source_request_path=str(request_path.resolve()), source_request_sha256=_sha256(request_path),
                resume_lineage_sha256=_sha256(lineage_path),
            )
        committed = {key: route_source[key] for key in fields}
        committed.update(
            schema_version=wc.COMMITTED_TERMINAL_SCHEMA, raw_review_path=str(raw_path),
            result_path=str(root / "committed-terminal-result.json"),
            immutable_sha256={
                name: source["immutable_sha256"][name]
                for name in ("endpoint.json", "envelope.json", "started.json", "ocrv-request.json")
            },
            recovery_terminal=recovery_terminal,
        )
        committed_path = root / "committed-terminal.json"
        committed_path.write_text(json.dumps(committed, sort_keys=True) + "\n", encoding="utf-8")
        wc._validate_committed_terminal_request(committed)
        completed = subprocess.run(
            command + ["checker-record-committed-terminal", "--request", str(committed_path),
                       "--sha256", _sha256(committed_path)],
            stdin=subprocess.DEVNULL, capture_output=True, check=False, env=os.environ.copy(),
            **windows_no_window_kwargs(),
        )
        if completed.returncode != 0:
            sys.stdout.buffer.write(completed.stdout)
            sys.stderr.buffer.write(completed.stderr)
            return completed.returncode
        recorded = json.loads(completed.stdout)
        if recorded.get("request_sha256") != _sha256(committed_path) or recorded.get(
            "d1_verdict"
        ) != result["verdict"]:
            raise ValueError("terminal-budget committed D1 response is not exact")
        status, event_type = "CHECKER_D1_RECORDED", recorded["d1_event_type"]
        suffix = _terminal_budget_post_d1_suffix(
            route_source, validated, result, attempt, root, command
        )

    outer = {
        "schema_version": (
            FRESH_RESULT_SCHEMA if fresh else FRESH_PARTIAL_RESULT_SCHEMA if fresh_partial else RESULT_SCHEMA
        ),
        "method_version": source["method_version"], "status": status,
        "run_id": source["run_id"], "cell_id": source["cell_id"], "attempt": source["attempt"],
        "candidate_message_id": source["candidate_message_id"],
        "checker_role_instance_id": source["checker_role_instance_id"],
        "checker_endpoint_version": source["checker_endpoint_version"],
        "recovery_invocation_id": recovery["recovery_invocation_id"],
        "request_sha256": _sha256(request_path),
        "capacity_revision_sha256": canonical_json_sha256(source["capacity_revision"]),
        "source_d1_incomplete_event_id": source["d1_incomplete_event_id"],
        "parent_session_id": session["session_id"], "child_session_id": child_session_id,
        "d1_verdict": result["verdict"], "d1_event_type": event_type, **suffix,
        "native_attempt_path": str(attempt),
        "native_result_path": str(attempt / "ocrv-result.json"),
    }
    if fresh:
        outer.update(
            source_rejection_sha256=recovery["source_rejection_sha256"],
            compatibility_authorization_sha256=canonical_json_sha256(recovery["owner_authorization"]),
        )
    else:
        outer.update(
            ocrv_transition_sha256=canonical_json_sha256(source["ocrv_transition"]),
            runtime_config_binding_sha256=canonical_json_sha256(source["runtime_config_binding"]),
        )
    encoded = (json.dumps(outer, sort_keys=True) + "\n").encode("utf-8")
    Path(recovery["result_path"]).write_bytes(encoded)
    sys.stdout.buffer.write(encoded)
    return 0


def _resume_terminal_budget(
    request: dict[str, object], request_path: Path, command: list[str]
) -> int:
    sys.path.insert(0, str(_transport_runtime_path(command)))
    from slk_transport.contracts import canonical_json_sha256
    from slk_transport.terminal_budget import claim_terminal_budget_source, validate

    validated = validate(request)
    _authenticate_terminal_budget(request, validated, str(request["recovery_invocation_id"]))
    if _ocrv_version() != validated["target_ocrv_version"]:
        raise ValueError("terminal-budget continuation OCRV version is not the approved target")
    mode, detail = _session_resume_mode(request, validated["session"])
    if mode != "RESUME_SESSION":
        raise ValueError("terminal-budget continuation requires the exact resumable OCRV Session")
    claim_terminal_budget_source(request)
    root = Path(request["recovery_root"]).resolve()
    root.mkdir(parents=True, exist_ok=True)
    (root / "session-show.json").write_text(json.dumps(detail, sort_keys=True) + "\n", encoding="utf-8")
    with (root / "resume-consumed.json").open("x", encoding="utf-8") as stream:
        json.dump({
            "request_sha256": _sha256(request_path),
            "source_d1_incomplete_event_id": request["d1_incomplete_event_id"],
            "capacity_revision_sha256": canonical_json_sha256(request["capacity_revision"]),
            "ocrv_transition_sha256": canonical_json_sha256(request["ocrv_transition"]),
        }, stream, sort_keys=True)
        stream.write("\n")
    return _run_terminal_budget_review(request, validated, request, request_path, command, fresh=False)


def _fresh_terminal_budget_review(
    request: dict[str, object], request_path: Path, command: list[str]
) -> int:
    sys.path.insert(0, str(_transport_runtime_path(command)))
    from slk_transport.contracts import canonical_json_sha256
    from slk_transport.terminal_budget_fresh import (
        claim_fresh_review_source, validate_fresh_review_request, verify_managed_target,
    )

    validated = validate_fresh_review_request(request)
    source = validated["source_request"]
    _authenticate_terminal_budget(source, validated, str(request["recovery_invocation_id"]))
    if _ocrv_version() != validated["target_ocrv_version"]:
        raise ValueError("fresh-review OCRV version is not the approved target")
    verify_managed_target(source)
    mode, detail = _session_resume_mode(source, source["ocrv_session"])
    expected_mode = (
        "FRESH_REVIEW"
        if validated["source_basis"] == "ZERO_TOKEN_PREDISPATCH_NON_RESUMABLE"
        else "RESUME_SESSION"
    )
    if mode != expected_mode:
        raise ValueError("fresh review source resumability changed after preparation")
    claim_fresh_review_source(request)
    root = Path(request["recovery_root"]).resolve()
    root.mkdir(parents=True, exist_ok=True)
    (root / "session-show.json").write_text(json.dumps(detail, sort_keys=True) + "\n", encoding="utf-8")
    with (root / "fresh-consumed.json").open("x", encoding="utf-8") as stream:
        json.dump({
            "request_sha256": _sha256(request_path),
            "source_request_sha256": request["source_request_sha256"],
            "source_rejection_sha256": request["source_rejection_sha256"],
            "authorization_sha256": canonical_json_sha256(request["owner_authorization"]),
        }, stream, sort_keys=True)
        stream.write("\n")
    return _run_terminal_budget_review(source, validated, request, request_path, command, fresh=True)


def _fresh_terminal_budget_partial(
    request: dict[str, object], request_path: Path, command: list[str]
) -> int:
    sys.path.insert(0, str(_transport_runtime_path(command)))
    from slk_transport.contracts import canonical_json_sha256
    from slk_transport.terminal_budget_fresh_partial import (
        claim_fresh_partial_source, validate_fresh_partial_request, verify_managed_target,
    )

    validated = validate_fresh_partial_request(request)
    source = validated["source_request"]
    _authenticate_terminal_budget(source, validated, str(request["recovery_invocation_id"]))
    if _ocrv_version() != validated["source_validated"]["target_ocrv_version"]:
        raise ValueError("fresh-partial OCRV version is not the approved target")
    verify_managed_target(request, validated)
    mode, detail = _session_resume_mode(source, source["ocrv_session"])
    if (
        mode != "RESUME_SESSION"
        or detail.get("summary") != validated["session_summary"]
        or not isinstance(detail.get("items"), list) or not detail["items"]
    ):
        raise ValueError("fresh-partial parent Session is no longer the exact resumable checkpoint")
    claim_fresh_partial_source(request)
    root = Path(request["recovery_root"]).resolve()
    root.mkdir(parents=True, exist_ok=True)
    (root / "session-show.json").write_text(json.dumps(detail, sort_keys=True) + "\n", encoding="utf-8")
    with (root / "resume-consumed.json").open("x", encoding="utf-8") as stream:
        json.dump({
            "request_sha256": _sha256(request_path),
            "parent_session_id": request["parent_session_id"],
            "capacity_revision_sha256": canonical_json_sha256(request["capacity_revision"]),
            "ocrv_transition_sha256": canonical_json_sha256(request["ocrv_transition"]),
        }, stream, sort_keys=True)
        stream.write("\n")
    return _run_terminal_budget_review(
        source, validated["source_validated"], request, request_path, command,
        fresh=False, fresh_partial=True,
    )


def _fresh_terminal_budget_partial_suffix(
    request: dict[str, object], request_path: Path, command: list[str],
) -> int:
    """Run only the deterministic suffix after an already-recorded fresh-partial D1."""

    sys.path.insert(0, str(_transport_runtime_path(command)))
    from slk_transport import worker_completion as wc
    from slk_transport.contracts import canonical_json_sha256
    from slk_transport.terminal_budget_fresh_partial import (
        RESULT_SCHEMA as FRESH_PARTIAL_RESULT_SCHEMA,
        claim_fresh_partial_suffix,
        validate_fresh_partial_suffix_source,
    )

    basis = validate_fresh_partial_suffix_source(request_path, request)
    source = basis["source"]
    checker = basis["committed_validated"]["checker"]
    if (
        os.environ.get("SLK_OCRV_RECOVERY_ROLE_INSTANCE_ID") != checker.role_instance_id
        or os.environ.get("SLK_OCRV_RECOVERY_ENDPOINT_VERSION")
        != str(checker.endpoint_version)
        or os.environ.get("SLK_OCRV_RECOVERY_INVOCATION_ID")
        != request["recovery_invocation_id"]
    ):
        raise ValueError("fresh-partial suffix is outside the original sealed Checker")
    authentication = wc._default_checker_authenticate(
        str(source["run_id"]), checker.role_instance_id,
        Path(str(source["checker_credential_path"])), list(source["state_command"]),
    )
    if (
        authentication.get("status") != "authenticated"
        or authentication.get("role") != "checker"
        or authentication.get("role_instance_id") != checker.role_instance_id
    ):
        raise ValueError("fresh-partial suffix Checker authentication failed")
    if authentication.get("runtime_revision") != basis["current_runtime_revision"]:
        basis = validate_fresh_partial_suffix_source(request_path, request)
        if authentication.get("runtime_revision") != basis["current_runtime_revision"]:
            raise ValueError("fresh-partial suffix runtime changed during authentication")
    claim_fresh_partial_suffix(request_path, request, basis)
    suffix = _terminal_budget_post_d1_suffix(
        source, basis["source_validated"], basis["native_result"],
        basis["native_attempt"], Path(str(request["recovery_root"])).resolve(), command,
    )
    native_result = basis["native_result"]
    receipt = basis["receipt"]
    outer = {
        "schema_version": FRESH_PARTIAL_RESULT_SCHEMA,
        "method_version": source["method_version"], "status": "CHECKER_D1_RECORDED",
        "run_id": source["run_id"], "cell_id": source["cell_id"],
        "attempt": source["attempt"], "candidate_message_id": source["candidate_message_id"],
        "checker_role_instance_id": source["checker_role_instance_id"],
        "checker_endpoint_version": source["checker_endpoint_version"],
        "recovery_invocation_id": request["recovery_invocation_id"],
        "request_sha256": _sha256(request_path),
        "capacity_revision_sha256": canonical_json_sha256(request["capacity_revision"]),
        "ocrv_transition_sha256": canonical_json_sha256(request["ocrv_transition"]),
        "runtime_config_binding_sha256": canonical_json_sha256(
            request["runtime_config_binding"]
        ),
        "source_d1_incomplete_event_id": source["d1_incomplete_event_id"],
        "d1_verdict": native_result["verdict"], "d1_event_type": receipt["d1_event_type"],
        **suffix,
        "parent_session_id": request["parent_session_id"],
        "child_session_id": native_result["review"]["session_id"],
        "native_attempt_path": str(basis["native_attempt"]),
        "native_result_path": str(basis["native_attempt"] / "ocrv-result.json"),
    }
    encoded = (json.dumps(outer, sort_keys=True) + "\n").encode("utf-8")
    Path(str(request["result_path"])).write_bytes(encoded)
    sys.stdout.buffer.write(encoded)
    return 0


def _resume_partial(
    request: dict[str, object], request_path: Path, command: list[str], *, consumed: bool = False,
    resume_later: bool = False, refine_zero_complete: bool = False,
) -> int:
    # The installed zipapp owns admission. This host alone handles its sealed role credential.
    sys.path.insert(0, command[-1])
    from slk_transport import worker_completion as wc
    from slk_transport.partial_review import (digest, read, records, validate_partial_source,
        validate_consumed_partial_attempt, validate_manifest, validate_resumed_raw, publish_aggregate)
    from slk_transport.adapters.ocrv import OcrvAdapter
    validated = wc._validate_incomplete_resume(request, consumed=consumed)
    checker = validated['checker']
    if (os.environ.get('SLK_OCRV_RECOVERY_ROLE_INSTANCE_ID') != checker.role_instance_id
        or os.environ.get('SLK_OCRV_RECOVERY_ENDPOINT_VERSION') != str(checker.endpoint_version)
        or os.environ.get('SLK_OCRV_RECOVERY_INVOCATION_ID') != request['recovery_invocation_id']):
        raise ValueError('partial resume is outside the original sealed Checker')
    authentication = wc._default_checker_authenticate(request['run_id'], checker.role_instance_id,
        Path(request['checker_credential_path']), request['state_command'])
    if (authentication.get('status') != 'authenticated' or authentication.get('role') != 'checker'
        or authentication.get('role_instance_id') != checker.role_instance_id):
        raise ValueError('partial resume Checker authentication failed before model start')
    if authentication.get('runtime_revision') != request['runtime_revision']:
        wc._rebind_overwatcher_only_committed_boundary(request, validated['frozen_projection'],
            wc._default_load_current_projection(request['run_id'], request['state_command']), authentication['runtime_revision'])
    if resume_later:
        return _resume_later_partial(request, request_path, command)
    if refine_zero_complete:
        return _refine_zero_complete_partial(request, request_path, command)
    basis = validate_partial_source(request, consumed=consumed)
    root = Path(request['recovery_root']).resolve()
    if consumed:
        existing = validate_consumed_partial_attempt(request, digest(request_path))
        attempt = existing['attempt']
        with (root / 'continue-consumed.json').open('x', encoding='utf-8') as stream:
            json.dump({'request_sha256': digest(request_path),
                       'existing_native_task_id': existing['result']['review_invocation_id']}, stream, sort_keys=True)
        correction = attempt / 'review-corrections/segment-001'
        correction.mkdir(parents=True, exist_ok=False)
        verdict, reasons = checker_adapter._classify(existing['raw'], 0)
        if verdict == 'INCOMPLETE':
            raise ValueError('completed first segment cannot be corrected from its preserved native evidence')
        corrected = {**existing['result'], 'verdict': verdict, 'reason_codes': reasons,
                     'findings': existing['raw']['comments']}
        corrected_path = correction / 'result.json'
        corrected_path.write_text(json.dumps(corrected, sort_keys=True)+'\n', encoding='utf-8')
        (correction / 'native-session.jsonl').write_bytes(existing['child_path'].read_bytes())
        receipt = {'schema_version': 'slk.ocrv-normalization-correction/v1',
            'cause': 'COMPLETED_REUSED_COVERAGE_WAS_OMITTED',
            'original_result_sha256': digest(existing['first'] / 'result.json'),
            'raw_review_sha256': digest(existing['first'] / 'ocrv-review.json'),
            'corrected_result_sha256': digest(corrected_path),
            'native_session_sha256': digest(correction / 'native-session.jsonl')}
        (correction / 'correction.json').write_text(json.dumps(receipt, sort_keys=True)+'\n', encoding='utf-8')
        envelope = wc.parse_delivery(read(basis['source'] / 'endpoint.json'), read(basis['source'] / 'envelope.json')).envelope
        OcrvAdapter().validate_existing_result(
            corrected_path, existing['first'] / 'request.json', envelope, {'PASS': 0, 'FAIL': 2}[verdict])
        values = [corrected]
        pending = list(enumerate(basis['segments'][1:], 2))
    else:
        mode, detail = _session_resume_mode(request, request['ocrv_session'])
        if (mode != 'RESUME_SESSION' or detail['summary'].get('run_manifest') != basis['manifest']
            or Path(str(detail['summary'].get('file_path',''))).resolve() != Path(request['ocrv_session']['session_record_path']).resolve()):
            raise ValueError('partial resume has no exact reusable native parent; fresh review is forbidden')
        root.mkdir(parents=True, exist_ok=False)
        (root / 'session-show.json').write_text(json.dumps(detail, sort_keys=True)+'\n', encoding='utf-8')
        marker = root.parent / 'partial-consumed.json'
        with marker.open('x', encoding='utf-8') as stream:
            json.dump({'recovery_invocation_id': request['recovery_invocation_id'], 'request_sha256': digest(request_path)}, stream, sort_keys=True)
        (root / 'resume-consumed.json').write_text(digest(request_path)+'\n', encoding='ascii')
        attempt = root / 'native-attempt'
        attempt.mkdir()
        values = []
        pending = list(enumerate(basis['segments'], 1))
    for ordinal, source_request in pending:
        item = attempt / 'review-segments' / f'segment-{ordinal:03d}'
        item.mkdir(parents=True)
        input_path = item / 'request.json'
        input_path.write_bytes(source_request.read_bytes())
        invocation = str(uuid.uuid4())
        os.environ['SLK_NATIVE_START_RECEIPT'] = str(item / 'started.json')
        os.environ['SLK_NATIVE_START_CONTEXT'] = json.dumps({'adapter': 'ocrv-checker', 'run_id': request['run_id'],
            'cell_id': request['cell_id'], 'message_id': request['candidate_message_id'],
            'request_sha256': request['payload_sha256'], 'native_request_sha256': digest(input_path)})
        code = checker_adapter.run(input_path, item / 'result.json', invocation_override=invocation,
            background_override=Path(request['background_path']) if ordinal == 1 else None,
            resume_session=request['ocrv_session']['session_id'] if ordinal == 1 else None)
        value = read(item / 'result.json')
        envelope = wc.parse_delivery(read(basis['source'] / 'endpoint.json'), read(basis['source'] / 'envelope.json')).envelope
        OcrvAdapter().validate_existing_result(item / 'result.json', input_path, envelope, code)
        start = wc.validate_native_start(item / 'started.json', adapter='ocrv-checker', run_id=request['run_id'],
            cell_id=request['cell_id'], message_id=request['candidate_message_id'], request_sha256=request['payload_sha256'],
            native_request_sha256=digest(input_path))
        if start['native_task']['kind'] != 'ocrv-review' or start['native_task']['id'] != value['review_invocation_id']:
            raise ValueError('partial continuation wrapper is not a native review start')
        if ordinal == 1: (attempt / 'started.json').write_bytes((item / 'started.json').read_bytes())
        if value['verdict'] == 'INCOMPLETE':
            raise ValueError('bounded partial continuation remains incomplete; no automatic retry or budget increase')
        raw = read(Path(value['artifacts']['raw_review']))
        validate_manifest(request, raw, read(input_path)['review_scope']['include_paths'], complete=True)
        child_detail = _run_ocrv_json(['session','show','--json','--repo',request['candidate_repository'],value['review']['session_id']])
        child_path = Path(child_detail['summary']['file_path']).resolve()
        if child_path != Path(request['ocrv_session']['session_record_path']).parent / (value['review']['session_id'] + '.jsonl'):
            raise ValueError('native child checkpoint is outside the frozen repository session store')
        (item / 'native-session.jsonl').write_bytes(child_path.read_bytes())
        if ordinal == 1:
            lineage = [row for row in records(item / 'native-session.jsonl') if row.get('type') == 'resume_lineage']
            if len(lineage) != 1: raise ValueError('native child lineage is absent or duplicated')
            validate_resumed_raw(basis, raw, lineage[0])
        values.append(value)
        if OcrvAdapter._has_blocking_finding(value): break
    return _finish_partial_terminal(request, request_path, command, attempt, values)


def _finish_partial_terminal(
    request: dict[str, object], request_path: Path, command: list[str], attempt: Path,
    values: list[dict[str, object]],
) -> int:
    from slk_transport import worker_completion as wc
    from slk_transport.partial_review import digest, publish_aggregate
    publish_aggregate(attempt, request, values)
    root = Path(request['recovery_root']).resolve()
    committed = {k:v for k,v in request.items() if k not in {'background_path','ocrv_session','recovery_root','partial_review'}}
    committed.update(schema_version=wc.COMMITTED_TERMINAL_SCHEMA, raw_review_path='unused',
        immutable_sha256={n:request['immutable_sha256'][n] for n in ('endpoint.json','envelope.json','started.json','ocrv-request.json')},
        partial_terminal={'resume_request_path': str(request_path), 'resume_request_sha256': digest(request_path),
            'evidence_sha256': {p.relative_to(attempt).as_posix(): digest(p) for p in attempt.rglob('*') if p.is_file()}})
    committed_path = root / 'committed-terminal.json'
    committed_path.write_text(json.dumps(committed, sort_keys=True)+'\n', encoding='utf-8')
    # All original hashes are checked again before consuming the formal verdict.
    wc._validate_committed_terminal_request(committed)
    completed = subprocess.run(command + ['checker-record-committed-terminal','--request',str(committed_path),'--sha256',digest(committed_path)],
        stdin=subprocess.DEVNULL, capture_output=True, check=False, env=os.environ.copy(), **windows_no_window_kwargs())
    if completed.returncode == 0:
        outer = json.loads(completed.stdout)
        if outer.get('request_sha256') != digest(committed_path): raise ValueError('partial terminal response hash mismatch')
        outer['request_sha256'] = digest(request_path)
        encoded = (json.dumps(outer, sort_keys=True)+'\n').encode('utf-8')
        Path(request['result_path']).write_bytes(encoded)
        sys.stdout.buffer.write(encoded)
    else: sys.stdout.buffer.write(completed.stdout)
    sys.stderr.buffer.write(completed.stderr)
    return completed.returncode


def _consume_existing_partial(
    request: dict[str, object], request_path: Path, command: list[str], evidence_root: Path,
) -> int:
    """Authenticate the original Checker, then derive D1 only from existing native terminals."""
    sys.path.insert(0, command[-1])
    from slk_transport import worker_completion as wc
    from slk_transport.partial_review import (
        digest, materialize_existing_partial_terminal, validate_existing_partial_completion)
    validated_request = wc._validate_incomplete_resume(request, consumed=True)
    checker = validated_request['checker']
    if (os.environ.get('SLK_OCRV_RECOVERY_ROLE_INSTANCE_ID') != checker.role_instance_id
        or os.environ.get('SLK_OCRV_RECOVERY_ENDPOINT_VERSION') != str(checker.endpoint_version)
        or os.environ.get('SLK_OCRV_RECOVERY_INVOCATION_ID') != request['recovery_invocation_id']):
        raise ValueError('existing partial consumption is outside the original sealed Checker')
    authentication = wc._default_checker_authenticate(
        request['run_id'], checker.role_instance_id,
        Path(request['checker_credential_path']), request['state_command'])
    if (authentication.get('status') != 'authenticated' or authentication.get('role') != 'checker'
        or authentication.get('role_instance_id') != checker.role_instance_id):
        raise ValueError('existing partial Checker authentication failed before evidence consumption')
    if authentication.get('runtime_revision') != request['runtime_revision']:
        wc._rebind_overwatcher_only_committed_boundary(
            request, validated_request['frozen_projection'],
            wc._default_load_current_projection(request['run_id'], request['state_command']),
            authentication['runtime_revision'])
    # Admission is repeated inside the sealed host before the first write.
    validate_existing_partial_completion(request, digest(request_path), evidence_root)
    root = Path(request['recovery_root']).resolve() / 'consume-existing-partial'
    if root.exists():
        raise ValueError('existing partial consumption is one-shot and already materialized')
    staging = root.with_name(root.name + '.staging-' + str(uuid.uuid4()))
    attempt = staging / 'native-attempt'
    materialize_existing_partial_terminal(request, request_path, evidence_root, attempt)
    staging.rename(root)
    attempt = root / 'native-attempt'
    committed = {key: value for key, value in request.items()
                 if key not in {'background_path', 'ocrv_session', 'recovery_root', 'partial_review'}}
    committed.update(schema_version=wc.COMMITTED_TERMINAL_SCHEMA, raw_review_path='unused',
        immutable_sha256={name: request['immutable_sha256'][name]
                          for name in ('endpoint.json', 'envelope.json', 'started.json', 'ocrv-request.json')},
        partial_terminal={'mode': 'EXISTING_PARTIAL_EVIDENCE',
            'resume_request_path': str(request_path), 'resume_request_sha256': digest(request_path),
            'source_evidence_root': str(evidence_root.resolve()),
            'evidence_index_sha256': digest(attempt / 'evidence-index.json'),
            'evidence_sha256': {path.relative_to(attempt).as_posix(): digest(path)
                                for path in attempt.rglob('*') if path.is_file()}})
    committed_path = root / 'committed-terminal.json'
    committed_path.write_text(json.dumps(committed, sort_keys=True) + '\n', encoding='utf-8')
    wc._validate_committed_terminal_request(committed)
    completed = subprocess.run(
        command + ['checker-record-committed-terminal', '--request', str(committed_path),
                   '--sha256', digest(committed_path)],
        stdin=subprocess.DEVNULL, capture_output=True, check=False, env=os.environ.copy(),
        **windows_no_window_kwargs())
    if completed.returncode == 0:
        outer = json.loads(completed.stdout)
        if outer.get('request_sha256') != digest(committed_path):
            raise ValueError('existing partial terminal response hash mismatch')
        outer['request_sha256'] = digest(request_path)
        encoded = (json.dumps(outer, sort_keys=True) + '\n').encode('utf-8')
        Path(request['result_path']).write_bytes(encoded)
        sys.stdout.buffer.write(encoded)
    else:
        sys.stdout.buffer.write(completed.stdout)
    sys.stderr.buffer.write(completed.stderr)
    return completed.returncode


def _resume_later_partial(
    request: dict[str, object], request_path: Path, command: list[str]
) -> int:
    from slk_transport import worker_completion as wc
    from slk_transport.partial_review import (digest, read, records,
        validate_completed_segment_resume, validate_consumed_partial_resume_attempt,
        validate_incomplete_segment_resume, validate_manifest)
    from slk_transport.adapters.ocrv import OcrvAdapter
    partial = validate_consumed_partial_resume_attempt(request, digest(request_path))
    root, attempt, second = partial['root'], partial['attempt'], partial['second']
    one_shot = root / 'resume-partial-segment-002'
    one_shot.mkdir(exist_ok=False)
    consumed = {
        'schema_version': 'slk.ocrv-partial-segment-resume-consumed/v1',
        'request_sha256': digest(request_path), 'segment_ordinal': 2,
        'partial_session_id': partial['partial_raw']['session_id'],
        'partial_result_sha256': digest(second / 'result.json'),
        'partial_raw_review_sha256': digest(second / 'ocrv-review.json'),
        'partial_native_session_sha256': digest(partial['partial_session_path']),
    }
    consumed_path = one_shot / 'consumed.json'
    consumed_path.write_text(json.dumps(consumed, sort_keys=True)+'\n', encoding='utf-8')
    input_path = second / 'request.json'
    invocation = str(uuid.uuid4())
    os.environ['SLK_NATIVE_START_RECEIPT'] = str(one_shot / 'started.json')
    os.environ['SLK_NATIVE_START_CONTEXT'] = json.dumps({'adapter':'ocrv-checker',
        'run_id':request['run_id'],'cell_id':request['cell_id'],'message_id':request['candidate_message_id'],
        'request_sha256':request['payload_sha256'],'native_request_sha256':digest(input_path)})
    code = checker_adapter.run(
        input_path, one_shot / 'result.json', invocation_override=invocation,
        background_override=second / 'd1-background.md',
        resume_session=partial['partial_raw']['session_id'])
    value = read(one_shot / 'result.json')
    envelope = wc.parse_delivery(
        read(partial['basis']['source'] / 'endpoint.json'),
        read(partial['basis']['source'] / 'envelope.json')).envelope
    OcrvAdapter().validate_existing_result(one_shot / 'result.json', input_path, envelope, code)
    start = wc.validate_native_start(one_shot / 'started.json', adapter='ocrv-checker',
        run_id=request['run_id'], cell_id=request['cell_id'], message_id=request['candidate_message_id'],
        request_sha256=request['payload_sha256'], native_request_sha256=digest(input_path))
    if start['native_task']['kind'] != 'ocrv-review' or start['native_task']['id'] != value['review_invocation_id']:
        raise ValueError('later partial continuation wrapper is not a native review start')
    raw = read(Path(value['artifacts']['raw_review']))
    child_detail = _run_ocrv_json(['session','show','--json','--repo',request['candidate_repository'],
                                   value['review']['session_id']])
    child_path = Path(child_detail['summary']['file_path']).resolve()
    expected_path = Path(request['ocrv_session']['session_record_path']).parent / (value['review']['session_id']+'.jsonl')
    if child_path != expected_path:
        raise ValueError('later partial child checkpoint is outside the frozen repository session store')
    native_copy = one_shot / 'native-session.jsonl'
    native_copy.write_bytes(child_path.read_bytes())
    lineage = [row for row in records(native_copy) if row.get('type') == 'resume_lineage']
    if len(lineage) != 1:
        raise ValueError('later partial native child lineage is absent or duplicated')
    scope = read(input_path)['review_scope']['include_paths']
    if value['verdict'] == 'INCOMPLETE':
        validate_manifest(request, raw, scope, complete=False)
        validate_incomplete_segment_resume(partial, raw, lineage[0])
        receipt = {**consumed, 'schema_version':'slk.ocrv-partial-segment-resume-result/v1',
            'status':'INCOMPLETE', 'child_session_id':value['review']['session_id'],
            'reason_codes':value['reason_codes'], 'resumed_result_sha256':digest(one_shot / 'result.json'),
            'resumed_raw_review_sha256':digest(one_shot / 'ocrv-review.json'),
            'resumed_native_session_sha256':digest(native_copy)}
        (one_shot / 'incomplete.json').write_text(json.dumps(receipt, sort_keys=True)+'\n', encoding='utf-8')
        raise ValueError('bounded segment 2 continuation remains incomplete; one-shot is consumed')
    validate_manifest(request, raw, scope, complete=True)
    validate_completed_segment_resume(partial, raw, lineage[0])
    complete = {**consumed, 'schema_version':'slk.ocrv-partial-segment-resume-result/v1',
        'status':'COMPLETE', 'child_session_id':value['review']['session_id'],
        'resumed_result_sha256':digest(one_shot / 'result.json'),
        'resumed_raw_review_sha256':digest(one_shot / 'ocrv-review.json'),
        'resumed_start_sha256':digest(one_shot / 'started.json'),
        'resumed_native_session_sha256':digest(native_copy)}
    complete_path = one_shot / 'complete.json'
    complete_path.write_text(json.dumps(complete, sort_keys=True)+'\n', encoding='utf-8')
    correction = attempt / 'review-corrections/segment-002'
    correction.mkdir(parents=True, exist_ok=False)
    for name in ('ocrv-review.json','started.json','native-activity.json','ocrv.stdout.txt','ocrv.stderr.txt','native-session.jsonl'):
        (correction / name).write_bytes((one_shot / name).read_bytes())
    (correction / 'd1-background.md').write_bytes((second / 'd1-background.md').read_bytes())
    corrected = {**value, 'artifacts':{**value['artifacts'],
        'raw_review':str(correction / 'ocrv-review.json'), 'stdout':str(correction / 'ocrv.stdout.txt'),
        'stderr':str(correction / 'ocrv.stderr.txt'), 'background':str(correction / 'd1-background.md')}}
    corrected_path = correction / 'result.json'
    corrected_path.write_text(json.dumps(corrected, sort_keys=True)+'\n', encoding='utf-8')
    correction_receipt = {
        'schema_version':'slk.ocrv-partial-segment-resume-correction/v1',
        'cause':'BUDGET_PARTIAL_SEGMENT_RESUMED',
        'original_partial_result_sha256':digest(second / 'result.json'),
        'original_partial_raw_review_sha256':digest(second / 'ocrv-review.json'),
        'original_partial_native_session_sha256':digest(partial['partial_session_path']),
        'one_shot_receipt_sha256':digest(complete_path),
        'resumed_native_result_sha256':digest(one_shot / 'result.json'),
        'resumed_raw_review_sha256':digest(one_shot / 'ocrv-review.json'),
        'resumed_start_sha256':digest(one_shot / 'started.json'),
        'corrected_result_sha256':digest(corrected_path),
        'native_session_sha256':digest(correction / 'native-session.jsonl'),
    }
    (correction / 'correction.json').write_text(json.dumps(correction_receipt, sort_keys=True)+'\n', encoding='utf-8')
    OcrvAdapter().validate_existing_result(corrected_path, input_path, envelope, {'PASS':0,'FAIL':2}[corrected['verdict']])
    return _finish_partial_terminal(
        request, request_path, command, attempt, [partial['corrected_first'], corrected])


def _refine_zero_complete_partial(
    request: dict[str, object], request_path: Path, command: list[str]
) -> int:
    """Review only the frozen failed paths after a segment completed none of them."""
    from slk_transport import worker_completion as wc
    from slk_transport.partial_review import (
        _complete_verdict, _dedupe_findings, digest, partial_blocking_failure_artifacts, read, validate_manifest,
        validate_zero_complete_refinement_attempt,
    )
    from slk_transport.adapters.ocrv import OcrvAdapter
    attempt_root = Path(request['recovery_root']).resolve() / 'native-attempt'
    final_partial = (attempt_root / 'review-segments/segment-003/result.json').is_file()
    partial = validate_zero_complete_refinement_attempt(
        request, digest(request_path), final_partial=final_partial)
    if final_partial:
        correction = partial['attempt'] / 'review-corrections/segment-003'
        correction.mkdir(parents=True, exist_ok=False)
        corrected, receipt = partial_blocking_failure_artifacts(request, partial, correction)
        (correction / 'result.json').write_text(
            json.dumps(corrected, sort_keys=True)+'\n', encoding='utf-8')
        (correction / 'correction.json').write_text(
            json.dumps(receipt, sort_keys=True)+'\n', encoding='utf-8')
        return _finish_partial_terminal(
            request, request_path, command, partial['attempt'],
            [partial['first']['result'], partial['composite'], corrected])
    root, attempt = partial['root'], partial['attempt']
    one_shot, correction = partial['one_shot'], partial['correction']
    one_shot.mkdir(exist_ok=False)
    consumed_path = one_shot / 'consumed.json'
    consumed_path.write_text(json.dumps(partial['consumed'], sort_keys=True)+'\n', encoding='utf-8')
    envelope = wc.parse_delivery(
        read(partial['source'] / 'endpoint.json'),
        read(partial['source'] / 'envelope.json')).envelope
    pieces, index_rows = [], []
    for ordinal, refined_request in enumerate(partial['refined_requests'], 1):
        item = one_shot / f'item-{ordinal:03d}'
        item.mkdir()
        input_path = item / 'request.json'
        input_path.write_text(json.dumps(refined_request, sort_keys=True)+'\n', encoding='utf-8')
        background = item / 'd1-background.md'
        background.write_bytes((partial['second']['root'] / 'd1-background.md').read_bytes())
        invocation = str(uuid.uuid4())
        os.environ['SLK_NATIVE_START_RECEIPT'] = str(item / 'started.json')
        os.environ['SLK_NATIVE_START_CONTEXT'] = json.dumps({
            'adapter':'ocrv-checker','run_id':request['run_id'],'cell_id':request['cell_id'],
            'message_id':request['candidate_message_id'],'request_sha256':request['payload_sha256'],
            'native_request_sha256':digest(input_path)})
        code = checker_adapter.run(
            input_path, item / 'result.json', invocation_override=invocation,
            background_override=background, resume_session=None)
        value = read(item / 'result.json')
        start = wc.validate_native_start(
            item / 'started.json', adapter='ocrv-checker', run_id=request['run_id'],
            cell_id=request['cell_id'], message_id=request['candidate_message_id'],
            request_sha256=request['payload_sha256'], native_request_sha256=digest(input_path))
        if start['native_task']['kind'] != 'ocrv-review' or start['native_task']['id'] != value['review_invocation_id']:
            raise ValueError('refined partial wrapper is not a native single-path review start')
        raw = read(Path(value['artifacts']['raw_review']))
        child_detail = _run_ocrv_json([
            'session','show','--json','--repo',request['candidate_repository'],value['review']['session_id']])
        child_path = Path(child_detail['summary']['file_path']).resolve()
        expected_path = (Path(request['ocrv_session']['session_record_path']).parent
                         / (value['review']['session_id']+'.jsonl'))
        if child_path != expected_path:
            raise ValueError('refined partial checkpoint is outside the frozen repository session store')
        native_copy = item / 'native-session.jsonl'
        native_copy.write_bytes(child_path.read_bytes())
        if value['verdict'] == 'INCOMPLETE':
            terminal = value.get('review', {}).get('status')
            if terminal not in {'partial','failed'}:
                raise ValueError('refined partial returned an invalid incomplete terminal')
            receipt = {**partial['consumed'],
                'schema_version':'slk.ocrv-zero-complete-refinement-result/v1',
                'status':'INCOMPLETE','failed_path':refined_request['review_scope']['include_paths'][0],
                'child_session_id':value['review']['session_id'],
                'result_sha256':digest(item / 'result.json'),
                'raw_review_sha256':digest(item / 'ocrv-review.json'),
                'native_session_sha256':digest(native_copy)}
            (one_shot / 'incomplete.json').write_text(
                json.dumps(receipt, sort_keys=True)+'\n', encoding='utf-8')
            raise ValueError('single-path refined review remains incomplete; no automatic retry or budget increase')
        OcrvAdapter().validate_existing_result(
            item / 'result.json', input_path, envelope, code)
        validate_manifest(request, raw, refined_request['review_scope']['include_paths'], complete=True)
        pieces.append((item, value, raw))
        index_rows.append({
            'ordinal':ordinal, 'path':refined_request['review_scope']['include_paths'][0],
            'request_sha256':digest(input_path), 'result_sha256':digest(item / 'result.json'),
            'raw_review_sha256':digest(item / 'ocrv-review.json'),
            'start_sha256':digest(item / 'started.json'),
            'activity_sha256':digest(item / 'native-activity.json'),
            'native_session_sha256':digest(native_copy),
        })
    correction.mkdir(parents=True, exist_ok=False)
    index = {'schema_version':'slk.ocrv-zero-complete-refinement-index/v1',
             'segment_ordinal':2,'items':index_rows}
    index_path = correction / 'evidence-index.json'
    index_path.write_text(json.dumps(index, sort_keys=True)+'\n', encoding='utf-8')
    findings = _dedupe_findings(
        partial['second']['findings'], *(raw.get('comments') for _item, _value, raw in pieces))
    verdict, reasons = _complete_verdict(findings)
    composite = {
        'schema_version':'slk.ocrv-d1-result/v1','run_id':request['run_id'],
        'cell_id':request['cell_id'],
        'review_invocation_id':f"refined-{request['recovery_invocation_id']}-segment-002",
        'verdict':verdict,'reason_codes':reasons,'findings':findings,
        'evidence':[digest(index_path)],
        'request_sha256':digest(partial['second']['input_path']),
        'review':{'status':'complete','provider':'dashscope-tokenplan','model':'qwen3.8-max',
                  'session_id':f"refined-{request['recovery_invocation_id']}-segment-002",
                  'exit_code':{'PASS':0,'FAIL':2}[verdict]},
        'artifacts':{'refinement_index':str(index_path)},
    }
    composite_path = correction / 'result.json'
    composite_path.write_text(json.dumps(composite, sort_keys=True)+'\n', encoding='utf-8')
    correction_receipt = {
        'schema_version':'slk.ocrv-zero-complete-refinement-correction/v1',
        'cause':'ZERO_COMPLETE_MULTI_PATH_BUDGET_REFINED_TO_SINGLE_PATHS',
        **{key:partial['consumed'][key] for key in (
            'original_result_sha256','original_raw_review_sha256','original_native_session_sha256')},
        'one_shot_consumed_sha256':digest(consumed_path),
        'evidence_index_sha256':digest(index_path),
        'corrected_result_sha256':digest(composite_path),
    }
    (correction / 'correction.json').write_text(
        json.dumps(correction_receipt, sort_keys=True)+'\n', encoding='utf-8')
    values = [partial['first']['result'], composite]
    if OcrvAdapter._has_blocking_finding(composite):
        return _finish_partial_terminal(request, request_path, command, attempt, values)
    ordinal, source_request = 3, partial['segments'][2]
    item = attempt / 'review-segments/segment-003'
    item.mkdir(parents=True)
    input_path = item / 'request.json'
    input_path.write_bytes(source_request.read_bytes())
    invocation = str(uuid.uuid4())
    os.environ['SLK_NATIVE_START_RECEIPT'] = str(item / 'started.json')
    os.environ['SLK_NATIVE_START_CONTEXT'] = json.dumps({
        'adapter':'ocrv-checker','run_id':request['run_id'],'cell_id':request['cell_id'],
        'message_id':request['candidate_message_id'],'request_sha256':request['payload_sha256'],
        'native_request_sha256':digest(input_path)})
    code = checker_adapter.run(input_path, item / 'result.json', invocation_override=invocation)
    value = read(item / 'result.json')
    if value['verdict'] == 'INCOMPLETE':
        raise ValueError('final frozen segment remains incomplete after refinement; no automatic retry')
    OcrvAdapter().validate_existing_result(item / 'result.json', input_path, envelope, code)
    wc.validate_native_start(
        item / 'started.json', adapter='ocrv-checker', run_id=request['run_id'],
        cell_id=request['cell_id'], message_id=request['candidate_message_id'],
        request_sha256=request['payload_sha256'], native_request_sha256=digest(input_path))
    raw = read(Path(value['artifacts']['raw_review']))
    validate_manifest(request, raw, read(input_path)['review_scope']['include_paths'], complete=True)
    child_detail = _run_ocrv_json([
        'session','show','--json','--repo',request['candidate_repository'],value['review']['session_id']])
    child_path = Path(child_detail['summary']['file_path']).resolve()
    expected_path = (Path(request['ocrv_session']['session_record_path']).parent
                     / (value['review']['session_id']+'.jsonl'))
    if child_path != expected_path:
        raise ValueError('final segment checkpoint is outside the frozen repository session store')
    (item / 'native-session.jsonl').write_bytes(child_path.read_bytes())
    values.append(value)
    return _finish_partial_terminal(request, request_path, command, attempt, values)

def main() -> int:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--slk-worker-recovery", action="store_true")
    mode.add_argument("--slk-existing-terminal", action="store_true")
    mode.add_argument("--slk-committed-terminal", action="store_true")
    mode.add_argument("--slk-resume-incomplete-checker", action="store_true")
    mode.add_argument("--slk-resume-terminal-budget", action="store_true")
    mode.add_argument("--slk-fresh-terminal-budget-review", action="store_true")
    mode.add_argument("--slk-resume-terminal-budget-fresh-partial", action="store_true")
    mode.add_argument("--slk-resume-terminal-budget-fresh-partial-suffix", action="store_true")
    mode.add_argument("--slk-continue-consumed-partial", action="store_true")
    mode.add_argument("--slk-resume-consumed-partial", action="store_true")
    mode.add_argument("--slk-refine-consumed-partial", action="store_true")
    mode.add_argument("--slk-consume-existing-partial", action="store_true")
    parser.add_argument("--request", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--evidence-root", type=Path)
    args = parser.parse_args()
    try:
        data = args.request.read_bytes()
        request = json.loads(data.decode("utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        print(f"SLK_OCRV_RECOVERY_INVALID: {exc}", file=sys.stderr)
        return 4
    expected_schema = (
        "slk.ocrv-terminal-budget-fresh-partial-request/v1"
        if args.slk_resume_terminal_budget_fresh_partial
        or args.slk_resume_terminal_budget_fresh_partial_suffix
        else "slk.ocrv-terminal-budget-fresh-review-request/v1"
        if args.slk_fresh_terminal_budget_review
        else "slk.ocrv-terminal-budget-resume-request/v1"
        if args.slk_resume_terminal_budget
        else "slk.ocrv-incomplete-checker-resume-request/v1"
        if args.slk_resume_incomplete_checker or args.slk_continue_consumed_partial
        or args.slk_resume_consumed_partial or args.slk_refine_consumed_partial
        or args.slk_consume_existing_partial
        else "slk.ocrv-committed-terminal-request/v1"
        if args.slk_committed_terminal
        else "slk.ocrv-worker-recovery-request/v1"
    )
    if (
        not isinstance(request, dict)
        or request.get("schema_version") != expected_schema
        or Path(str(request.get("result_path", ""))).resolve() != args.output.resolve()
    ):
        print("SLK_OCRV_RECOVERY_INVALID: request identity mismatch", file=sys.stderr)
        return 4
    try:
        command = _request_transport_command(
            request, fresh=(
                args.slk_fresh_terminal_budget_review
                or args.slk_resume_terminal_budget_fresh_partial
                or args.slk_resume_terminal_budget_fresh_partial_suffix
            )
        )
    except ValueError as exc:
        print(f"SLK_OCRV_RECOVERY_INVALID: {exc}", file=sys.stderr)
        return 4
    environment = os.environ.copy()
    environment.pop("SLK_ROLE_CREDENTIAL", None)
    environment.pop("SLK_OVERWATCHER_CREDENTIAL", None)
    if (args.slk_existing_terminal or args.slk_committed_terminal or args.slk_resume_incomplete_checker
        or args.slk_resume_terminal_budget
        or args.slk_fresh_terminal_budget_review
        or args.slk_resume_terminal_budget_fresh_partial
        or args.slk_resume_terminal_budget_fresh_partial_suffix
        or args.slk_continue_consumed_partial or args.slk_resume_consumed_partial
        or args.slk_refine_consumed_partial
        or args.slk_consume_existing_partial):
        environment.pop("SLK_NATIVE_START_RECEIPT", None)
        environment.pop("SLK_NATIVE_START_CONTEXT", None)
    if args.slk_worker_recovery:
        try:
            _publish_start(
                hashlib.sha256(data).hexdigest(),
                str(request.get("recovery_invocation_id", "")),
            )
        except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
            print(f"SLK_OCRV_RECOVERY_INVALID: {exc}", file=sys.stderr)
            return 4
    try:
        if args.slk_consume_existing_partial:
            if args.evidence_root is None:
                raise ValueError('existing partial evidence root is required')
            return _consume_existing_partial(
                request, args.request.resolve(), command, args.evidence_root.resolve())
        if args.slk_resume_terminal_budget:
            return _resume_terminal_budget(request, args.request.resolve(), command)
        if args.slk_fresh_terminal_budget_review:
            return _fresh_terminal_budget_review(request, args.request.resolve(), command)
        if args.slk_resume_terminal_budget_fresh_partial:
            return _fresh_terminal_budget_partial(request, args.request.resolve(), command)
        if args.slk_resume_terminal_budget_fresh_partial_suffix:
            return _fresh_terminal_budget_partial_suffix(
                request, args.request.resolve(), command
            )
        if args.slk_resume_consumed_partial:
            return _resume_partial(request, args.request.resolve(), command, consumed=True, resume_later=True)
        if args.slk_refine_consumed_partial:
            return _resume_partial(
                request, args.request.resolve(), command, consumed=True, refine_zero_complete=True)
        if args.slk_continue_consumed_partial:
            return _resume_partial(request, args.request.resolve(), command, consumed=True)
        if args.slk_resume_incomplete_checker:
            return _resume_incomplete(request, args.request.resolve(), command)
        internal_command = (
            "checker-record-committed-terminal"
            if args.slk_committed_terminal
            else "checker-recover-worker"
        )
        completed = subprocess.run(
            command
            + [
                internal_command,
                "--request",
                str(args.request.resolve()),
                "--sha256",
                hashlib.sha256(data).hexdigest(),
            ],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            env=environment,
            **windows_no_window_kwargs(),
        )
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(f"SLK_OCRV_RECOVERY_HOST_FAILED: {exc}", file=sys.stderr)
        return 5
    if completed.stdout:
        sys.stdout.write(completed.stdout)
    if completed.stderr:
        sys.stderr.write(completed.stderr)
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
