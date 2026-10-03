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
        "slk.ocrv-incomplete-checker-resume-request/v1"
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
    command = request.get("transport_command")
    if not isinstance(command, list) or not command or not all(isinstance(item, str) and item for item in command):
        print("SLK_OCRV_RECOVERY_INVALID: transport command is invalid", file=sys.stderr)
        return 4
    environment = os.environ.copy()
    environment.pop("SLK_ROLE_CREDENTIAL", None)
    environment.pop("SLK_OVERWATCHER_CREDENTIAL", None)
    if (args.slk_existing_terminal or args.slk_committed_terminal or args.slk_resume_incomplete_checker
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
