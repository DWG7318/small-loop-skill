"""Frozen OCRV compression recovery through the existing management-return route."""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Any, Mapping

from .evidence import Attempt


SCHEMA = "slk.ocrv-context-recovery-plan/v1"
FIELDS = {"schema_version", "run_id", "cell_id", "candidate_message_id",
          "source_d1_incomplete_event_id", "sources", "groups"}
SOURCE_FIELDS = {"request", "result", "raw_review", "session_record"}
COMPRESSION_REASON = "stopped because context compression exceeded its threshold"
INPUT_FIELDS = {'mode', 'requested_head', 'resolved_base', 'resolved_head', 'exact_range', 'source_artifact_sha256'}


def artifact_digest(selected: Mapping[str, Mapping[str, str]]) -> str:
    """OCRV v1.12.12 sourceArtifactSHA256: sorted IDs, length-framed fingerprints."""
    result = hashlib.sha256()
    for item in sorted(selected.values(), key=lambda x: x['item_id']):
        for key in ('item_id', 'fingerprint'):
            value = item[key].encode('utf-8')
            result.update(len(value).to_bytes(8, 'big')); result.update(value)
    return result.hexdigest()


def git_identities(request: Mapping[str, Any], input_value: Mapping[str, Any], paths: list[str]) -> dict[str, dict[str, str]]:
    """Reproduce the native immutable commit diff locally; never read model bodies."""
    from .process import windows_no_window_kwargs
    head = request['candidate']['commit']
    base = input_value.get('resolved_base')
    if (set(input_value) != INPUT_FIELDS or input_value.get('mode') != 'commit'
        or any(input_value.get(k) != head for k in ('requested_head', 'resolved_head'))
        or not isinstance(base, str) or re.fullmatch('[0-9a-f]{40}', base) is None
        or input_value.get('exact_range') != base + '..' + head):
        raise ValueError('context native immutable input is invalid')
    def git(*args: str) -> str:
        process = subprocess.run(['git', '-C', request['repository'], *args],
            stdin=subprocess.DEVNULL, capture_output=True, timeout=120, check=False,
            **windows_no_window_kwargs())
        if process.returncode:
            raise ValueError('context immutable Git source is unavailable')
        return process.stdout.decode('utf-8')
    if git('rev-list', '--parents', '-n', '1', '--end-of-options', head).split() != [head, base]:
        raise ValueError('context native candidate parent changed')
    text = git('-c', 'core.quotepath=false', 'diff', '--no-ext-diff', '--no-textconv',
               '--find-renames', '--src-prefix=a/', '--dst-prefix=b/', '--no-color',
               '-U3', '--end-of-options', base, head, '--')
    found: dict[str, dict[str, str]] = {}
    old, new, lines, in_hunk = None, None, [], False
    def flush() -> None:
        if new in paths:
            patch = '\n'.join(lines).rstrip('\r\n')
            item = {'path': new,
                'item_id': hashlib.sha256(('review\0commit\0' + old + '\0' + new).encode()).hexdigest(),
                'fingerprint': hashlib.sha256(('commit\0' + old + '\0' + new + '\0' + patch).encode()).hexdigest()}
            if new in found:
                raise ValueError('context native diff has duplicate paths')
            found[new] = item
    for line in text.split('\n'):
        line = line.removesuffix('\r')
        if line.startswith('diff --git '):
            flush()
            match = re.fullmatch(r'diff --git a/(.+?) b/(.+)', line)
            if match is None:
                raise ValueError('context native diff path encoding is unsupported')
            old, new = match.groups(); lines, in_hunk = [], False
        if old is None:
            continue
        if line.startswith('@@'):
            in_hunk = True
        elif not in_hunk and line.startswith('index '):
            continue
        elif not in_hunk and line.startswith('rename from '):
            old = line.removeprefix('rename from ')
        elif not in_hunk and line.startswith('rename to '):
            new = line.removeprefix('rename to ')
        elif not in_hunk and line == '+++ /dev/null':
            new = '/dev/null'
        lines.append(line)
    flush()
    if set(found) != set(paths):
        raise ValueError('context native diff does not cover the exact selection')
    return found


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
            "groups": plan["groups"], "paths": paths, "request": old}


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
    expected = git_identities(basis['request'], parent['input'], list(basis['selected']))
    child_input = manifest.get('input', {})
    if (expected != basis['selected'] or parent['input'].get('source_artifact_sha256') != artifact_digest(expected)
        or set(child_input) != INPUT_FIELDS
        or any(child_input.get(k) != parent['input'][k] for k in INPUT_FIELDS - {'source_artifact_sha256'})
        or child_input.get('source_artifact_sha256') != artifact_digest({p: expected[p] for p in scoped_paths})):
        raise ValueError('context segment source artifact does not match the exact immutable diff')
    if (manifest.get("schema_version") != "ocr.run-manifest/v1" or manifest.get("operation") != "review"
        or manifest.get("run_id") != raw.get("session_id")
        or raw.get("session_id") != value["review"]["session_id"] or raw.get("session_id") == basis["raw"]["session_id"]
        or manifest.get("parent_run_id") is not None or reused or coverage.get("waived")
        or manifest.get("repository") != parent.get("repository")
        or selected != {p: basis["selected"][p] for p in scoped_paths}
        or set(done) & set(failed) or {**done, **failed} != selected
        or any(manifest.get("execution", {}).get(k) != parent["execution"].get(k)
               for k in ("provider", "model", "runtime_config_sha256", "ocr_version", "configured_concurrency"))
        or not isinstance(raw.get("comments"), list)
        or any(not isinstance(x, dict) or str(x.get("severity", "")).upper()
               not in {"INFO", "LOW", "MEDIUM", "HIGH", "BLOCKER", "CRITICAL"} for x in raw["comments"])
        or (value["verdict"] == "PASS" and any(str(x.get("severity", "")).upper()
            in {"MEDIUM", "HIGH", "BLOCKER", "CRITICAL"} for x in raw["comments"]))
        or (value["verdict"] != "INCOMPLETE" and
            (failed or done != selected or manifest.get("terminal_state") != "complete" or raw.get("status") != "complete"))):
        raise ValueError("context segment changed the candidate, coverage or native identity")


def validate_terminal(source: Path, session_record: Path, session_sha256: str) -> dict[str, Any]:
    """Admit only a proven first-segment blocker rejected by the old scope comparison."""
    from .contracts import Envelope, DeliveryResult
    from .adapters.ocrv import OcrvAdapter
    from .native_activity import validate_native_start
    envelope = Envelope.from_dict(read(source / 'envelope.json'))
    failed = DeliveryResult.from_dict(read(source / 'failed.json'))
    if (envelope.payload_type != 'D1_MANAGEMENT_RETURN' or envelope.receiver_role != 'checker'
        or failed.message_id != envelope.message_id or failed.run_id != envelope.run_id
        or failed.adapter != 'ocrv-checker' or failed.status != 'failed'
        or failed.error_code != 'OCRV_CONTEXT_RECOVERY_INVALID'
        or any((source / name).exists() for name in ('completed.json', 'ocrv-result.json'))
        or [p.name for p in sorted((source / 'review-segments').iterdir())] != ['segment-001']
        or not session_record.is_absolute() or digest(session_record) != session_sha256):
        raise ValueError('context consumption is not the exact frozen first-segment failure')
    full = OcrvAdapter()._candidate_request(envelope)
    if read(source / 'ocrv-preflight-request.json') != full:
        raise ValueError('context full request changed')
    plans = [Path(p) for p in envelope.payload['management_evidence_refs']
             if Path(p).suffix.lower() == '.json' and read(Path(p)).get('schema_version') == SCHEMA]
    if len(plans) != 1 or read(source / 'ocrv-context-recovery-plan.json') != read(plans[0]):
        raise ValueError('context consumption plan changed')
    plan = read(plans[0]); basis = validate(plan, full, envelope.payload)
    all_paths = read(source / 'ocrv-preflight.json')['preview']['selected_paths']
    if len(all_paths) != len(set(all_paths)) or set(all_paths) != set(basis['selected']):
        raise ValueError('context full preview scope changed')
    segment = source / 'review-segments/segment-001'
    request = read(segment / 'request.json'); scope = plan['groups'][0]
    expected = OcrvAdapter._make_review_segment(full, all_paths, scope, full['d1_criteria'],
        full['review_scope']['criterion_ids'], f'1/{len(plan["groups"])}')
    if request != expected:
        raise ValueError('context first segment request changed')
    result = OcrvAdapter().validate_existing_result(segment / 'result.json', segment / 'request.json', envelope, 2)
    validate_segment(basis, result, scope)
    raw_path = Path(result['artifacts']['raw_review']); raw = read(raw_path)
    comments = [{k: v for k, v in item.items() if k not in {'thinking', 'reasoning', 'analysis'}} for item in raw['comments']]
    if (result['reason_codes'] != ['OCR_BLOCKING_FINDINGS_PRESENT'] or result['findings'] != comments
        or not any(str(item.get('severity', '')).upper() in {'MEDIUM', 'HIGH', 'BLOCKER', 'CRITICAL'} for item in comments)
        or session_record.stem != raw['session_id']):
        raise ValueError('context native blocking verdict or findings changed')
    started = validate_native_start(source / 'started.json', adapter='ocrv-checker', run_id=envelope.run_id,
        cell_id=envelope.cell_id, message_id=envelope.message_id, request_sha256=envelope.payload_sha256)
    if (started['native_task']['kind'] != 'ocrv-review' or started['native_task']['id'] != result['review_invocation_id']
        or started['native_request_sha256'] != digest(segment / 'request.json')):
        raise ValueError('context first segment has no matching original native start')
    starts, ends, checkpoints = [], [], {}
    with session_record.open(encoding='utf-8-sig') as stream:
        for line in stream:
            if not line.endswith('\n'):
                raise ValueError('context child native record is torn')
            row = json.loads(line)
            if not isinstance(row, dict):
                raise ValueError('context child native record is invalid')
            if row.get('type') == 'session_start': starts.append(row)
            elif row.get('type') == 'session_end': ends.append(row)
            elif row.get('type') == 'review_item_done':
                key = row.get('filePath')
                if key in checkpoints: raise ValueError('context child checkpoint is duplicated')
                checkpoints[key] = row
            elif row.get('type') in {'review_item_failed', 'review_item_reused'}:
                raise ValueError('context completed child has an incompatible checkpoint')
    if (len(starts) != 1 or len(ends) != 1 or starts[0].get('sessionId') != raw['session_id']
        or starts[0].get('diffCommit') != full['candidate']['commit'] or starts[0].get('model') != 'qwen3.8-max'
        or Path(str(starts[0].get('cwd'))).resolve() != Path(full['repository']).resolve()
        or ends[0].get('sessionId') != raw['session_id'] or ends[0].get('run_manifest') != raw['manifest']
        or set(checkpoints) != set(scope)):
        raise ValueError('context child native terminal or coverage is unproven')
    native_comments = []
    for path in scope:
        row = checkpoints[path]
        if (row.get('sessionId') != raw['session_id'] or row.get('fingerprint') != basis['selected'][path]['fingerprint']
            or not isinstance(row.get('comments', []), list)):
            raise ValueError('context child native checkpoint changed')
        native_comments.extend(row.get('comments', []))
    if sorted(map(lambda x: json.dumps(x, sort_keys=True), native_comments)) != sorted(map(lambda x: json.dumps(x, sort_keys=True), raw['comments'])):
        raise ValueError('context child native findings changed')
    paths = {str(p.resolve()): digest(p) for p in (
        source / 'endpoint.json', source / 'envelope.json', source / 'failed.json', source / 'started.json',
        source / 'ocrv-preflight-request.json', source / 'ocrv-preflight.json', source / 'ocrv-context-recovery-plan.json',
        segment / 'request.json', segment / 'result.json', raw_path, session_record, plans[0])}
    paths.update({str(p): digest(p) for p in basis['paths'].values()})
    return {**basis, 'envelope': envelope, 'full_request': full, 'all_paths': all_paths,
        'result': result, 'scope': scope, 'source_hashes': paths, 'plan': plan, 'plan_path': plans[0]}


def materialize_terminal(source: Path, output: Path, basis: Mapping[str, Any]) -> None:
    """Derive an accurate FAIL aggregate without changing any source or invoking a model."""
    import shutil
    from .contracts import DeliveryResult, canonical_json_sha256
    from .worker_completion import _stable_id, _write_or_reuse_stable_request
    result, envelope = basis['result'], basis['envelope']
    output.mkdir(parents=True, exist_ok=True)
    for name in ('endpoint.json', 'envelope.json', 'started.json',
                 'review-segments/segment-001/request.json', 'review-segments/segment-001/result.json'):
        path = output / name; path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            if path.read_bytes() != (source / name).read_bytes(): raise ValueError('context derived evidence drift')
        else: shutil.copyfile(source / name, path)
    findings = [{k: v for k, v in item.items() if k not in {'thinking', 'reasoning', 'analysis'}} for item in basis['raw']['comments']]
    findings += result['findings']
    aggregate = {'schema_version': 'slk.ocrv-d1-aggregate/v1', 'run_id': envelope.run_id, 'cell_id': envelope.cell_id,
        'verdict': 'FAIL', 'reason_codes': result['reason_codes'], 'planned_segment_count': len(basis['groups']),
        'completed_segment_count': 1, 'stopped_on_blocking_finding': True, 'findings': findings,
        'segments': [{'ordinal': 1, 'request_sha256': result['request_sha256'],
            'result_sha256': digest(source / 'review-segments/segment-001/result.json'), 'verdict': 'FAIL',
            'reason_codes': result['reason_codes'], 'review_invocation_id': result['review_invocation_id'],
            'session_id': result['review']['session_id']}],
        'context_recovery': {'plan_sha256': digest(basis['plan_path']), 'sources': basis['plan']['sources'],
            'parent_session_id': basis['raw']['session_id'], 'reused': basis['reused'],
            'selected': list(basis['selected'].values()),
            'reviewed_paths': basis['scope'], 'not_reviewed_paths': [p for group in basis['groups'][1:] for p in group],
            'consumed_source_sha256': basis['source_hashes']}}
    _write_or_reuse_stable_request(output / 'ocrv-aggregate.json', aggregate)
    scope = {'include_paths': basis['all_paths'], 'exclude_paths': [],
             'criterion_ids': basis['full_request']['review_scope']['criterion_ids']}
    scope['scope_sha256'] = canonical_json_sha256(scope)
    _write_or_reuse_stable_request(output / 'ocrv-request.json', {**basis['full_request'], 'review_scope': scope})
    invocation = _stable_id(envelope.message_id, 'context-terminal-consumption')
    formal = {**result, 'review_invocation_id': invocation, 'findings': findings,
        'review': {**result['review'], 'session_id': 'ocrv-aggregate-' + invocation, 'exit_code': 2},
        'request_sha256': digest(output / 'ocrv-request.json'),
        'evidence': [digest(output / 'ocrv-aggregate.json')], 'artifacts': {'aggregate': 'ocrv-aggregate.json'}}
    _write_or_reuse_stable_request(output / 'ocrv-result.json', formal)
    terminal = DeliveryResult('slk.transport-result/v1', envelope.message_id, envelope.run_id, 'ocrv-checker',
        'completed', {'run_id': envelope.run_id, 'cell_id': envelope.cell_id, 'review_invocation_id': invocation,
            'session_id': formal['review']['session_id'], 'provider': 'dashscope-tokenplan', 'model': 'qwen3.8-max',
            'verdict': 'FAIL', 'exit_code': 2, 'review_segment_count': 1}, None,
        ('started.json', 'ocrv-request.json', 'ocrv-result.json', 'ocrv-aggregate.json'))
    _write_or_reuse_stable_request(output / 'completed.json', terminal.to_dict())
