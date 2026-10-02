"""Evidence-only admission for the existing sealed OCRV partial continuation."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from .contracts import canonical_json_sha256


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding='utf-8-sig'))
    if not isinstance(value, dict):
        raise ValueError('partial continuation evidence is not an object')
    return value


def records(path: Path) -> list[dict[str, Any]]:
    data = path.read_text(encoding='utf-8-sig')
    if not data.endswith('\n'):
        raise ValueError('native checkpoint contains a torn record')
    rows = [json.loads(line) for line in data.splitlines()]
    if not rows or any(not isinstance(row, dict) for row in rows):
        raise ValueError('native checkpoint contains an invalid record')
    return rows


def identities(items: object) -> set[tuple[str, str, str]]:
    if not isinstance(items, list):
        raise ValueError('native coverage is not a list')
    result = set()
    for item in items:
        if not isinstance(item, dict):
            raise ValueError('native coverage item is invalid')
        identity = tuple(item.get(key) for key in ('item_id', 'path', 'fingerprint'))
        if not all(isinstance(v, str) and v for v in identity) or len(identity[2]) != 64:
            raise ValueError('native coverage fingerprint is missing')
        if identity in result:
            raise ValueError('native coverage item is duplicated')
        result.add(identity)
    return result


def validate_manifest(request: Mapping[str, Any], raw: Mapping[str, Any], scope: list[str], *, complete: bool) -> dict[str, Any]:
    manifest = raw.get('manifest')
    if not isinstance(manifest, dict):
        raise ValueError('native review manifest is absent')
    terminal = 'complete' if complete else 'partial'
    execution, input_value, coverage = (manifest.get(k) for k in ('execution', 'input', 'coverage'))
    if (raw.get('status') != terminal or manifest.get('terminal_state') != terminal
        or manifest.get('schema_version') != 'ocr.run-manifest/v1' or manifest.get('operation') != 'review'
        or manifest.get('run_id') != raw.get('session_id') or not isinstance(execution, dict)
        or execution.get('provider') != 'dashscope-tokenplan' or execution.get('model') != 'qwen3.8-max'
        or not isinstance(input_value, dict) or input_value.get('mode') != 'commit'
        or input_value.get('requested_head') != request['candidate_commit']
        or input_value.get('resolved_head') != request['candidate_commit']
        or input_value.get('resolved_base') != request['candidate_parent']
        or input_value.get('exact_range') != f"{request['candidate_parent']}..{request['candidate_commit']}"
        or not isinstance(coverage, dict)):
        raise ValueError('native manifest candidate, model or terminal identity drift')
    selected = identities(coverage.get('selected'))
    completed = identities(coverage.get('completed'))
    reused = identities(coverage.get('reused'))
    failed = identities(coverage.get('failed'))
    if not selected or {row[1] for row in selected} != set(scope) or coverage.get('waived') != []:
        raise ValueError('native manifest scope is not exact')
    if (completed & reused or not (completed | reused | failed) <= selected
        or (complete and (failed or completed | reused != selected))):
        raise ValueError('native review coverage is incomplete or ambiguous')
    return manifest


def validate_partial_source(request: Mapping[str, Any], *, consumed: bool = False) -> dict[str, Any]:
    source = Path(str(request['native_attempt_path'])).resolve()
    basis = request['partial_review']
    session = request['ocrv_session']
    if (not isinstance(basis, dict) or set(basis) != {'schema_version', 'planned_segment_count',
            'd1_started_event_id', 'd1_incomplete_event_id', 'manifest_sha256', 'source_sha256'}
        or basis['schema_version'] != 'slk.ocrv-partial-continuation/v1'
        or type(basis['planned_segment_count']) is not int or basis['planned_segment_count'] != 3
        or any((source / name).exists() for name in ('completed.json', 'ocrv-result.json'))
        or (not consumed and ((Path(str(request['recovery_root'])) / 'resume-consumed.json').exists()
                             or (source / 'resume-incomplete-checker/partial-consumed.json').exists()))
        or session.get('aborted') is not False or session.get('selected_files') != 2 or session.get('completed_files') != 1):
        raise ValueError('partial continuation is not the closed first-of-three budget boundary')
    names = ['failed.json', 'ocrv-preflight-request.json', 'ocrv-preflight.json',
             'review-segments/segment-001/request.json', 'review-segments/segment-001/preflight.json',
             'review-segments/segment-001/result.json']
    names += [f'review-preflight-proposals/proposal-{n:03d}/{f}.json' for n in range(1,4) for f in ('request','preflight')]
    first = source / 'review-segments/segment-001'
    result = read(first / 'result.json')
    raw_path = Path(str(result.get('artifacts', {}).get('raw_review', ''))).resolve()
    paths = {**{name: source / name for name in names}, 'raw_review': raw_path}
    hashes = basis['source_sha256']
    if (not isinstance(hashes, dict) or set(hashes) != set(paths)
        or any(not path.is_file() or digest(path) != hashes[name] for name, path in paths.items())
        or digest(Path(session['session_record_path'])) != session['session_record_sha256']):
        raise ValueError('partial source hash drift')
    terminal = read(source / 'failed.json')
    if (terminal.get('schema_version') != 'slk.transport-result/v1' or terminal.get('status') != 'failed'
        or terminal.get('error_code') != 'OCRV_REVIEW_INCOMPLETE' or terminal.get('adapter') != 'ocrv-checker'
        or terminal.get('message_id') != request['candidate_message_id'] or terminal.get('run_id') != request['run_id']
        or terminal.get('native_identity') != {'run_id': request['run_id'], 'cell_id': request['cell_id'],
           'review_segment_count': 3, 'completed_review_segments': 1}):
        raise ValueError('original terminal is not the exact partial result')
    projection_path = Path(request['runtime_projection_path'])
    if digest(projection_path) != request['runtime_projection_sha256']:
        raise ValueError('partial runtime projection hash drift')
    events = read(projection_path)['events']
    for key, kind in [('d1_started_event_id', 'D1_STARTED'), ('d1_incomplete_event_id', 'D1_INCOMPLETE')]:
        matches = [event for event in events if event.get('event_id') == basis[key]]
        if len(matches) != 1:
            raise ValueError('original D1 lineage event is absent or duplicated')
        event = matches[0]
        details = json.loads(event['details_json'])
        if (event.get('event_type') != kind or event.get('cell_id') != request['cell_id']
            or event.get('go_id') != request['go_id'] or event.get('attempt') != request['attempt']
            or event.get('author_role_instance_id') != request['checker_role_instance_id']
            or details.get('candidate_message_id') != request['candidate_message_id']
            or details.get('native_start_sha256') != digest(source / 'started.json')
            or (kind == 'D1_INCOMPLETE' and details.get('native_terminal_sha256') != digest(source / 'failed.json'))):
            raise ValueError('original D1 lineage does not bind the partial native evidence')
    full = read(source / 'ocrv-preflight-request.json')
    all_paths = read(source / 'ocrv-preflight.json')['preview']['selected_paths']
    segments, covered = [], []
    from .adapters.ocrv import OcrvAdapter
    for n in range(1, 4):
        proposal = source / 'review-preflight-proposals' / f'proposal-{n:03d}'
        value, check = read(proposal / 'request.json'), read(proposal / 'preflight.json')
        scope = value['review_scope']
        expected_segment = OcrvAdapter._make_review_segment(full, all_paths, scope['include_paths'],
            full['d1_criteria'], [f'D1-{i:03d}' for i in range(1,len(full['d1_criteria'])+1)], f'{n}/3')
        if (value != expected_segment
            or value.get('candidate') != {'kind': 'commit', 'commit': request['candidate_commit']}
            or value.get('run_id') != request['run_id'] or value.get('cell_id') != request['cell_id']
            or Path(value['repository']).resolve() != Path(request['candidate_repository']).resolve()
            or check.get('status') != 'READY' or check.get('request_sha256') != digest(proposal / 'request.json')
            or check['preview']['selected_paths'] != scope['include_paths']
            or not scope['include_paths'] or len(scope['include_paths']) > value['capacity']['max_segment_paths']
            or set(scope['exclude_paths']) != set(all_paths) - set(scope['include_paths'])
            or scope['criterion_ids'] != [f'D1-{i:03d}' for i in range(1, len(value['d1_criteria'])+1)]
            or scope['scope_sha256'] != canonical_json_sha256({k:v for k,v in scope.items() if k != 'scope_sha256'})
            or (n > 1 and (source / 'review-segments' / f'segment-{n:03d}').exists())):
            raise ValueError('frozen segment scope, criteria, capacity or unstarted status drift')
        covered += scope['include_paths']
        segments.append(proposal / 'request.json')
    if len(covered) != len(set(covered)) or set(covered) != set(all_paths):
        raise ValueError('frozen segments do not partition the original scope')
    if (digest(first / 'request.json') != digest(segments[0]) or result.get('request_sha256') != digest(segments[0])
        or result.get('verdict') != 'INCOMPLETE' or result.get('run_id') != request['run_id']
        or result.get('cell_id') != request['cell_id'] or result.get('review', {}).get('session_id') != session['session_id']):
        raise ValueError('first partial segment identity drift')
    raw = read(raw_path)
    manifest = validate_manifest(request, raw, read(segments[0])['review_scope']['include_paths'], complete=False)
    coverage = manifest['coverage']
    if (manifest['run_id'] != session['session_id'] or canonical_json_sha256(manifest) != basis['manifest_sha256']
        or not coverage['completed'] or coverage['reused'] or not coverage['failed']
        or any(item.get('classification') != 'budget' for item in coverage['failed'])
        or identities(coverage['completed']) | identities(coverage['failed']) != identities(coverage['selected'])):
        raise ValueError('source is not a genuine budget-partial manifest')
    replay = records(Path(session['session_record_path']))
    ends = [row for row in replay if row.get('type') == 'session_end']
    checkpoints = {}
    for row in replay:
        if row.get('type') in {'review_item_done', 'review_item_reused'}:
            checkpoints[row.get('fingerprint')] = row
        elif row.get('type') == 'review_item_failed':
            checkpoints.pop(row.get('fingerprint'), None)
    if len(ends) != 1 or ends[0].get('run_manifest') != manifest:
        raise ValueError('parent checkpoint manifest is not the frozen raw manifest')
    for item in coverage['completed']:
        checkpoint = checkpoints.get(item['fingerprint'], {})
        if (checkpoint.get('sessionId') != session['session_id'] or checkpoint.get('filePath') != item['path']
            or not isinstance(checkpoint.get('comments'), list)):
            raise ValueError('completed fingerprint has no reusable native checkpoint')
    return {'source': source, 'segments': segments, 'raw': raw, 'manifest': manifest,
            'completed': coverage['completed'], 'session': session}


def validate_resumed_raw(basis: Mapping[str, Any], raw: Mapping[str, Any], lineage: Mapping[str, Any]) -> None:
    old = basis['manifest']
    parent = old['run_id']
    child = raw.get('session_id')
    expected = {'schema_version': 'ocr.resume-lineage/v1', 'parent_run_id': parent, 'run_id': child,
                'source_provider': 'dashscope-tokenplan', 'source_model': 'qwen3.8-max',
                'target_provider': 'dashscope-tokenplan', 'target_model': 'qwen3.8-max'}
    if not child or child == parent or any(lineage.get(k) != v for k,v in expected.items()):
        raise ValueError('resume must identify the truthful native parent/child lineage')
    manifest = raw['manifest']
    if (manifest.get('input') != old['input'] or manifest.get('repository') != old.get('repository')
        or any(manifest.get('execution', {}).get(k) != old['execution'].get(k)
               for k in ('provider', 'model', 'rule_config_sha256'))
        or identities(manifest['coverage']['selected']) != identities(old['coverage']['selected'])
        or not identities(old['coverage']['completed']) <= identities(manifest['coverage']['reused'])):
        raise ValueError('resumed native result did not reuse the frozen completed fingerprints')


def validate_consumed_partial_attempt(request: Mapping[str, Any], request_sha256: str) -> dict[str, Any]:
    """Admit the one real segment already completed before the mapper failed."""
    basis = validate_partial_source(request, consumed=True)
    root = Path(str(request['recovery_root'])).resolve()
    attempt = root / 'native-attempt'
    first = attempt / 'review-segments/segment-001'
    marker = root.parent / 'partial-consumed.json'
    if (read(marker) != {'recovery_invocation_id': request['recovery_invocation_id'],
                         'request_sha256': request_sha256}
        or (root / 'resume-consumed.json').read_text(encoding='ascii').strip() != request_sha256
        or (root / 'continue-consumed.json').exists()
        or any((attempt / 'review-segments' / f'segment-{n:03d}').exists() for n in (2, 3))
        or any((attempt / name).exists() for name in ('ocrv-result.json', 'ocrv-aggregate.json', 'completed.json'))):
        raise ValueError('consumed continuation identity is absent, repeated, or already advanced')
    required = ('request.json', 'result.json', 'ocrv-review.json', 'started.json',
                'native-activity.json', 'ocrv.stdout.txt', 'ocrv.stderr.txt')
    if (not all((first / name).is_file() for name in required)
        or digest(first / 'request.json') != digest(basis['segments'][0])):
        raise ValueError('completed first segment evidence is incomplete')
    result = read(first / 'result.json')
    raw_path = Path(str(result.get('artifacts', {}).get('raw_review', ''))).resolve()
    if raw_path != (first / 'ocrv-review.json').resolve():
        raise ValueError('completed first segment raw review escaped its sealed evidence root')
    raw = read(raw_path)
    manifest = validate_manifest(request, raw, read(first / 'request.json')['review_scope']['include_paths'], complete=True)
    comments = raw.get('comments')
    if (result.get('schema_version') != 'slk.ocrv-d1-result/v1'
        or result.get('run_id') != request['run_id'] or result.get('cell_id') != request['cell_id']
        or result.get('verdict') != 'INCOMPLETE' or result.get('reason_codes') != ['OCR_COVERAGE_INCOMPLETE']
        or result.get('request_sha256') != digest(first / 'request.json')
        or result.get('findings') != comments or not isinstance(comments, list)
        or result.get('review') != {'status': 'complete', 'provider': 'dashscope-tokenplan',
            'model': 'qwen3.8-max', 'session_id': raw.get('session_id'), 'exit_code': 0}
        or raw.get('llm') != {'provider': 'dashscope-tokenplan', 'model': 'qwen3.8-max'}
        or raw.get('tool_calls', {}).get('failure') != 0):
        raise ValueError('completed first segment was not solely misclassified by the reused coverage bug')
    start = read(first / 'started.json')
    activity = read(first / 'native-activity.json')
    expected_start = {'schema_version': 'slk.native-start/v2', 'status': 'STARTED', 'adapter': 'ocrv-checker',
        'run_id': request['run_id'], 'cell_id': request['cell_id'], 'message_id': request['candidate_message_id'],
        'request_sha256': request['payload_sha256'], 'native_request_sha256': digest(first / 'request.json')}
    if (any(start.get(k) != v for k, v in expected_start.items())
        or start.get('native_task', {}).get('kind') != 'ocrv-review'
        or start.get('native_task', {}).get('id') != result.get('review_invocation_id')
        or activity.get('schema_version') != 'slk.native-task-activity/v1'
        or any(activity.get(k) != v for k, v in {'adapter': 'ocrv-checker', 'run_id': request['run_id'],
            'cell_id': request['cell_id'], 'message_id': request['candidate_message_id']}.items())
        or activity.get('native_task_id') != result.get('review_invocation_id')
        or activity.get('status') != 'COMPLETED'
        or activity.get('last_event', {}).get('kind') != 'OCRV_PROCESS_EXITED'
        or activity.get('last_event', {}).get('exit_code') != 0):
        raise ValueError('completed first segment native start or terminal activity is not exact')
    child_path = Path(str(request['ocrv_session']['session_record_path'])).resolve().parent / f"{raw['session_id']}.jsonl"
    child_rows = records(child_path)
    ends = [row for row in child_rows if row.get('type') == 'session_end']
    lineage = [row for row in child_rows if row.get('type') == 'resume_lineage']
    if len(ends) != 1 or ends[0].get('run_manifest') != manifest or len(lineage) != 1:
        raise ValueError('completed first segment native child record is incomplete')
    validate_resumed_raw(basis, raw, lineage[0])
    return {'basis': basis, 'root': root, 'attempt': attempt, 'first': first,
            'result': result, 'raw': raw, 'child_path': child_path}


def effective_segment_root(root: Path, ordinal: int) -> Path:
    correction = root / 'review-corrections' / f'segment-{ordinal:03d}'
    return correction if correction.is_dir() else root / 'review-segments' / f'segment-{ordinal:03d}'


def publish_aggregate(root: Path, request: Mapping[str, Any], segment_results: list[Mapping[str, Any]]) -> None:
    """Use the existing aggregate evidence format; never promote partial coverage."""
    from .adapters.ocrv import OcrvAdapter
    reasons, findings, compact = [], [], []
    for ordinal, value in enumerate(segment_results, 1):
        for code in value['reason_codes']:
            if code not in reasons: reasons.append(code)
        findings.extend({'severity': str(item.get('severity', 'UNKNOWN')),
                         'finding_sha256': canonical_json_sha256(item)} for item in value['findings'])
        item_root = effective_segment_root(root, ordinal)
        compact.append({'ordinal': ordinal, 'request_sha256': value['request_sha256'],
            'result_sha256': digest(item_root / 'result.json'),
            'verdict': value['verdict'], 'reason_codes': value['reason_codes'],
            'review_invocation_id': value['review_invocation_id'], 'session_id': value['review']['session_id']})
    stopped = OcrvAdapter._has_blocking_finding(segment_results[-1])
    if len(segment_results) != 3 and not stopped:
        raise ValueError('unfinished frozen review cannot become a formal D1')
    verdict = 'FAIL' if any(value['verdict'] == 'FAIL' for value in segment_results) else 'PASS'
    aggregate = {'schema_version': 'slk.ocrv-d1-aggregate/v1', 'run_id': request['run_id'], 'cell_id': request['cell_id'],
        'verdict': verdict, 'reason_codes': reasons, 'planned_segment_count': 3,
        'completed_segment_count': len(segment_results), 'stopped_on_blocking_finding': stopped,
        'segments': compact, 'findings': findings}
    def write(name, value): (root / name).write_text(json.dumps(value, sort_keys=True)+'\n', encoding='utf-8')
    full = read(Path(request['native_attempt_path']) / 'ocrv-preflight-request.json')
    paths = read(Path(request['native_attempt_path']) / 'ocrv-preflight.json')['preview']['selected_paths']
    scope = {'include_paths': paths, 'exclude_paths': [],
             'criterion_ids': [f'D1-{i:03d}' for i in range(1, len(full['d1_criteria'])+1)]}
    scope['scope_sha256'] = canonical_json_sha256(scope)
    write('ocrv-request.json', {**full, 'review_scope': scope})
    write('ocrv-aggregate.json', aggregate)
    code = {'PASS':0, 'FAIL':2}[verdict]
    result = {'schema_version': 'slk.ocrv-d1-result/v1', 'run_id': request['run_id'], 'cell_id': request['cell_id'],
        'review_invocation_id': f"aggregate-{request['recovery_invocation_id']}", 'verdict': verdict,
        'reason_codes': reasons, 'findings': findings, 'review': {'status': 'complete', 'provider': 'dashscope-tokenplan',
        'model': 'qwen3.8-max', 'session_id': f"aggregate-{request['recovery_invocation_id']}", 'exit_code': code},
        'evidence': [digest(root / 'ocrv-aggregate.json')], 'request_sha256': digest(root / 'ocrv-request.json'),
        'artifacts': {'aggregate': 'ocrv-aggregate.json'}}
    write('ocrv-result.json', result)
    write('completed.json', {'schema_version': 'slk.transport-result/v1', 'message_id': request['candidate_message_id'],
        'run_id': request['run_id'], 'adapter': 'ocrv-checker', 'status': 'completed',
        'native_identity': {'run_id': request['run_id'], 'cell_id': request['cell_id'],
        'review_invocation_id': result['review_invocation_id'], **{k:result['review'][k] for k in ('session_id','provider','model')},
        'verdict': verdict, 'exit_code': code, 'review_segment_count': len(segment_results)}, 'error_code': None,
        'evidence': ['started.json', 'ocrv-request.json', 'ocrv-result.json', 'ocrv-aggregate.json']})


def validate_partial_terminal(request: Mapping[str, Any]) -> dict[str, Any]:
    from . import worker_completion as wc
    from .adapters.ocrv import OcrvAdapter
    resume_path = Path(request['partial_terminal']['resume_request_path']).resolve()
    if digest(resume_path) != request['partial_terminal']['resume_request_sha256']:
        raise ValueError('partial terminal resume request hash drift')
    original = read(resume_path)
    basis = validate_partial_source(original, consumed=True)
    source_request = {k:v for k,v in original.items() if k not in {'background_path','ocrv_session','recovery_root','partial_review'}}
    source_request.update(schema_version=wc.COMMITTED_TERMINAL_SCHEMA, raw_review_path='unused',
                          immutable_sha256={n:original['immutable_sha256'][n] for n in ('endpoint.json','envelope.json','started.json','ocrv-request.json')})
    common = wc._validate_committed_terminal_request(source_request, source_only=True, partial_review=original['partial_review'])
    expected = {**source_request, 'partial_terminal': request['partial_terminal']}
    if request != expected or set(request['partial_terminal']) != {'resume_request_path','resume_request_sha256','evidence_sha256'}:
        raise ValueError('partial terminal altered the admitted scope')
    root = Path(original['recovery_root']) / 'native-attempt'
    hashes = request['partial_terminal']['evidence_sha256']
    actual = {p.relative_to(root).as_posix(): digest(p) for p in root.rglob('*') if p.is_file()}
    if hashes != actual or read(Path(original['recovery_root']).parent / 'partial-consumed.json') != {
        'recovery_invocation_id': original['recovery_invocation_id'], 'request_sha256': digest(resume_path)}:
        raise ValueError('partial terminal evidence or one-shot lineage drift')
    envelope = wc.parse_delivery(read(basis['source'] / 'endpoint.json'), read(basis['source'] / 'envelope.json')).envelope
    aggregate, values = read(root / 'ocrv-aggregate.json'), []
    for n, segment in enumerate(aggregate['segments'], 1):
        source_root = root / 'review-segments' / f'segment-{n:03d}'
        item_root = effective_segment_root(root, n)
        input_path, result_path = source_root / 'request.json', item_root / 'result.json'
        if digest(input_path) != digest(basis['segments'][n-1]) or segment['result_sha256'] != digest(result_path):
            raise ValueError('continuation segment request or result drift')
        result = read(result_path)
        if item_root != source_root:
            correction = read(item_root / 'correction.json')
            if correction != {'schema_version': 'slk.ocrv-normalization-correction/v1',
                'cause': 'COMPLETED_REUSED_COVERAGE_WAS_OMITTED',
                'original_result_sha256': digest(source_root / 'result.json'),
                'raw_review_sha256': digest(source_root / 'ocrv-review.json'),
                'corrected_result_sha256': digest(result_path),
                'native_session_sha256': digest(item_root / 'native-session.jsonl')}:
                raise ValueError('normalization correction receipt does not bind preserved evidence')
        OcrvAdapter().validate_existing_result(result_path, input_path, envelope, {'PASS':0,'FAIL':2}[result['verdict']])
        raw = read(Path(result['artifacts']['raw_review']))
        validate_manifest(original, raw, read(input_path)['review_scope']['include_paths'], complete=True)
        comments = raw.get('comments')
        if (not isinstance(comments, list) or comments != result['findings'] or result['review']['exit_code'] != 0
            or raw.get('llm', {}).get('provider') != result['review']['provider']
            or raw.get('llm', {}).get('model') != result['review']['model']
            or raw.get('tool_calls', {}).get('failure', 0) != 0
            or any(not isinstance(c, dict) or not isinstance(c.get('severity'), str) or c['severity'].strip().upper() not in
                   {'INFO','LOW','MEDIUM','HIGH','BLOCKER','CRITICAL'} for c in comments)
            or result['verdict'] != ('FAIL' if any(str(c['severity']).strip().upper() in
                    {'MEDIUM','HIGH','BLOCKER','CRITICAL'} for c in comments) else 'PASS')):
            raise ValueError('native findings, model or verdict were altered before D1 consumption')
        wc.validate_native_start(source_root / 'started.json', adapter='ocrv-checker', run_id=original['run_id'],
            cell_id=original['cell_id'], message_id=original['candidate_message_id'], request_sha256=original['payload_sha256'],
            native_request_sha256=digest(input_path))
        start = read(source_root / 'started.json')
        if start['native_task']['kind'] != 'ocrv-review' or start['native_task']['id'] != result['review_invocation_id']:
            raise ValueError('aggregate contains a wrapper or mismatched native start')
        native_path = Path(original['ocrv_session']['session_record_path']).parent / (result['review']['session_id'] + '.jsonl')
        if digest(native_path) != digest(item_root / 'native-session.jsonl'):
            raise ValueError('aggregate checkpoint does not match the native repository session store')
        child_rows = records(item_root / 'native-session.jsonl')
        ends = [row for row in child_rows if row.get('type') == 'session_end']
        if len(ends) != 1 or ends[0].get('run_manifest') != raw['manifest']:
            raise ValueError('aggregate raw manifest is not the native session terminal manifest')
        if n == 1:
            lineage = [row for row in child_rows if row.get('type') == 'resume_lineage']
            if len(lineage) != 1: raise ValueError('native resume lineage is absent or duplicated')
            validate_resumed_raw(basis, raw, lineage[0])
        values.append(result)
    if not values or len(values) > 3 or (len(values) != 3 and not OcrvAdapter._has_blocking_finding(values[-1])):
        raise ValueError('partial continuation has unfinished coverage')
    if digest(root / 'started.json') != digest(root / 'review-segments/segment-001/started.json'):
        raise ValueError('aggregate start is not the original continuation segment start')
    verdict = 'FAIL' if any(value['verdict'] == 'FAIL' for value in values) else 'PASS'
    if aggregate['verdict'] != verdict or aggregate['completed_segment_count'] != len(values):
        raise ValueError('aggregate falsely promotes the native results')
    return {**common, 'activation': {'native_attempt_path': str(root), 'candidate_message_id': original['candidate_message_id'],
        'runtime_revision': original['runtime_revision'], 'token_sequence': original['token_sequence']},
        'continuation': {**{k:original[k] for k in ('run_id','go_id','cell_id','attempt','plan_revision','checker_endpoint','state_command')},
        'partial_correction_event_id': original['partial_review']['d1_incomplete_event_id'],
        'partial_recovery_invocation_id': original['recovery_invocation_id']}}
