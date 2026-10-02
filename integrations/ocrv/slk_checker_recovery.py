#!/usr/bin/env python3
"""Narrow OCRV launcher for one authenticated SLK Worker-completion recovery."""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
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


def _resume_partial(
    request: dict[str, object], request_path: Path, command: list[str], *, consumed: bool = False
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
    publish_aggregate(attempt, request, values)
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

def main() -> int:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--slk-worker-recovery", action="store_true")
    mode.add_argument("--slk-existing-terminal", action="store_true")
    mode.add_argument("--slk-committed-terminal", action="store_true")
    mode.add_argument("--slk-resume-incomplete-checker", action="store_true")
    mode.add_argument("--slk-continue-consumed-partial", action="store_true")
    parser.add_argument("--request", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        data = args.request.read_bytes()
        request = json.loads(data.decode("utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        print(f"SLK_OCRV_RECOVERY_INVALID: {exc}", file=sys.stderr)
        return 4
    expected_schema = (
        "slk.ocrv-incomplete-checker-resume-request/v1"
        if args.slk_resume_incomplete_checker or args.slk_continue_consumed_partial
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
    command = request.get("transport_command")
    if not isinstance(command, list) or not command or not all(isinstance(item, str) and item for item in command):
        print("SLK_OCRV_RECOVERY_INVALID: transport command is invalid", file=sys.stderr)
        return 4
    environment = os.environ.copy()
    environment.pop("SLK_ROLE_CREDENTIAL", None)
    environment.pop("SLK_OVERWATCHER_CREDENTIAL", None)
    if (args.slk_existing_terminal or args.slk_committed_terminal or args.slk_resume_incomplete_checker
        or args.slk_continue_consumed_partial):
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
