from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from test_incomplete_checker_resume import resume_fixture
from test_committed_checker_terminal import sha256, write_json


def partial_fixture(tmp_path: Path):
    request, request_path = resume_fixture(tmp_path)
    source = Path(request['native_attempt_path'])
    original = json.loads((source / 'ocrv-request.json').read_text())
    preflight = json.loads((source / 'ocrv-preflight.json').read_text())
    paths = ['src/a.py', 'src/b.py', 'src/c.py', 'src/d.py', 'src/e.py', 'src/f.py']
    from slk_transport.contracts import canonical_json_sha256
    write_json(source / 'ocrv-preflight-request.json', original)
    preflight['preview']['selected_paths'] = paths
    write_json(source / 'ocrv-preflight.json', preflight)
    for ordinal in range(1, 4):
        segment = copy.deepcopy(original)
        scope = {'include_paths': paths[(ordinal-1)*2:ordinal*2],
                 'exclude_paths': [p for p in paths if p not in paths[(ordinal-1)*2:ordinal*2]],
                 'criterion_ids': ['D1-001']}
        scope['scope_sha256'] = canonical_json_sha256(scope)
        segment['review_scope'] = scope
        segment['cell_goal'] = f"[SLK review segment {ordinal}/3] Changed-path scope: {', '.join(scope['include_paths'])}. Original goal: {original['cell_goal']}"
        proposal = source / 'review-preflight-proposals' / f'proposal-{ordinal:03d}'
        write_json(proposal / 'request.json', segment)
        check = copy.deepcopy(preflight)
        check['preview']['selected_paths'] = scope['include_paths']
        check['request_sha256'] = sha256(proposal / 'request.json')
        write_json(proposal / 'preflight.json', check)
        if ordinal == 1:
            write_json(source / 'review-segments/segment-001/request.json', segment)
            write_json(source / 'review-segments/segment-001/preflight.json', check)
    (source / 'ocrv-request.json').unlink()
    first = source / 'review-segments/segment-001'
    selected = [{'item_id': 'item-a', 'path': paths[0], 'fingerprint': 'a'*64},
                {'item_id': 'item-b', 'path': paths[1], 'fingerprint': 'b'*64}]
    manifest = {'schema_version': 'ocr.run-manifest/v1', 'run_id': 'ocrv-session-1',
                'operation': 'review', 'terminal_state': 'partial', 'repository': {},
                'input': {'mode': 'commit', 'requested_head': request['candidate_commit'],
                          'resolved_head': request['candidate_commit'], 'resolved_base': request['candidate_parent'],
                          'exact_range': f"{request['candidate_parent']}..{request['candidate_commit']}",
                          'source_artifact_sha256': 'c'*64},
                'execution': {'version': 'v1.12.7', 'provider': 'dashscope-tokenplan', 'model': 'qwen3.8-max',
                              'rule_config_sha256': 'd'*64, 'runtime_config_sha256': 'e'*64},
                'coverage': {'selected': selected, 'completed': [selected[1]], 'reused': [],
                             'failed': [{**selected[0], 'classification': 'budget'}], 'waived': []}}
    raw = write_json(tmp_path / 'partial-native/ocrv-review.json', {'status': 'partial', 'session_id': 'ocrv-session-1',
                     'manifest': manifest, 'comments': []})
    result = {'schema_version': 'slk.ocrv-d1-result/v1', 'run_id': request['run_id'], 'cell_id': request['cell_id'],
              'verdict': 'INCOMPLETE', 'request_sha256': sha256(first / 'request.json'), 'review_invocation_id': 'review-1',
              'review': {'status': 'partial', 'provider': 'dashscope-tokenplan', 'model': 'qwen3.8-max',
                         'session_id': 'ocrv-session-1', 'exit_code': 0}, 'artifacts': {'raw_review': str(raw)},
              'reason_codes': ['OCRV_REVIEW_INCOMPLETE'], 'findings': [], 'evidence': []}
    write_json(first / 'result.json', result)
    failed = {'schema_version': 'slk.transport-result/v1', 'message_id': request['candidate_message_id'],
              'run_id': request['run_id'], 'adapter': 'ocrv-checker', 'status': 'failed',
              'native_identity': {'run_id': request['run_id'], 'cell_id': request['cell_id'],
                                  'review_segment_count': 3, 'completed_review_segments': 1},
              'error_code': 'OCRV_REVIEW_INCOMPLETE', 'evidence': ['started.json']}
    write_json(source / 'failed.json', failed)
    # Original start and central hashes bind the first segment, not a nonexistent root request.
    start = json.loads((source / 'started.json').read_text())
    start['native_request_sha256'] = sha256(first / 'request.json')
    write_json(source / 'started.json', start)
    commit_path = Path(request['commit_request_path'])
    commit = json.loads(commit_path.read_text())
    commit['start_evidence']['sha256'] = sha256(source / 'started.json')
    write_json(commit_path, commit)
    request['commit_request_sha256'] = sha256(commit_path)
    projection_path = Path(request['runtime_projection_path'])
    projection = json.loads(projection_path.read_text())
    projection['events'][1]['details_json'] = json.dumps({**json.loads(projection['events'][1]['details_json']),
                                                       'start_evidence_sha256': sha256(source / 'started.json')})
    for event_id, kind in [('d1-start', 'D1_STARTED'), ('d1-incomplete', 'D1_INCOMPLETE')]:
        projection['events'].append({'event_id': event_id, 'event_type': kind, 'go_id': request['go_id'],
                                     'cell_id': request['cell_id'], 'attempt': request['attempt'],
                                     'author_role_instance_id': request['checker_role_instance_id'],
                                     'details_json': json.dumps({'candidate_message_id': request['candidate_message_id'],
                                                               'native_start_sha256': sha256(source / 'started.json'),
                                                               'native_terminal_sha256': sha256(source / 'failed.json')})})
    projection['administrative_snapshot']['latest_event_id'] = 'd1-incomplete'
    write_json(projection_path, projection)
    request['runtime_projection_sha256'] = sha256(projection_path)
    session = request['ocrv_session']
    session.update({'aborted': False, 'selected_files': 2, 'completed_files': 1})
    record = Path(session['session_record_path'])
    record.write_text('\n'.join(json.dumps(row) for row in [
        {'type': 'session_start', 'sessionId': session['session_id'], 'diffCommit': request['candidate_commit']},
        {'type': 'review_item_done', 'sessionId': session['session_id'], 'filePath': paths[1], 'fingerprint': 'b'*64,
         'comments': []}, {'type': 'session_end', 'sessionId': session['session_id'], 'run_manifest': manifest}])+'\n')
    session['session_record_sha256'] = sha256(record)
    request['immutable_sha256'].update({'started.json': sha256(source / 'started.json'),
        'ocrv-request.json': sha256(first / 'request.json'), 'ocrv-preflight.json': sha256(first / 'preflight.json'),
        'session-record': sha256(record)})
    names = ['failed.json', 'ocrv-preflight-request.json', 'ocrv-preflight.json',
             'review-segments/segment-001/request.json', 'review-segments/segment-001/preflight.json',
             'review-segments/segment-001/result.json']
    names += [f'review-preflight-proposals/proposal-{n:03d}/{f}.json' for n in range(1,4) for f in ('request','preflight')]
    request['partial_review'] = {'schema_version': 'slk.ocrv-partial-continuation/v1', 'planned_segment_count': 3,
                                'd1_started_event_id': 'd1-start', 'd1_incomplete_event_id': 'd1-incomplete',
                                'manifest_sha256': canonical_json_sha256(manifest),
                                'source_sha256': {**{n: sha256(source / n) for n in names}, 'raw_review': sha256(raw)}}
    write_json(request_path, request)
    return request, request_path


def test_real_budget_partial_layout_is_admitted_without_rewriting_source(tmp_path):
    from slk_transport.partial_review import validate_partial_source
    request, _ = partial_fixture(tmp_path)
    before = {p: p.read_bytes() for p in Path(request['native_attempt_path']).rglob('*') if p.is_file()}
    value = validate_partial_source(request)
    assert len(value['segments']) == 3
    assert value['completed'][0]['path'] == 'src/b.py'
    assert all(p.read_bytes() == content for p, content in before.items())


def test_existing_public_resume_accepts_real_partial_boundary(tmp_path, monkeypatch):
    from slk_transport import worker_completion
    request, path = partial_fixture(tmp_path)
    from test_incomplete_checker_resume import dead_activity
    monkeypatch.setattr(worker_completion, 'inspect_native_activity', dead_activity)
    monkeypatch.setattr(worker_completion, '_run_sealed_checker_terminal',
                        lambda *a, **k: {'status': 'SEALED_CHECKER_SELECTED'})
    assert worker_completion.resume_incomplete_checker(path, request_sha256=sha256(path))['status'] == 'SEALED_CHECKER_SELECTED'


def test_prepare_only_returns_scoped_receipt_without_launch(tmp_path, monkeypatch):
    from slk_transport import worker_completion as wc
    from test_incomplete_checker_resume import dead_activity
    request, path = partial_fixture(tmp_path)
    monkeypatch.setattr(wc, 'inspect_native_activity', dead_activity)
    monkeypatch.setattr(wc, '_run_sealed_checker_terminal', lambda *a,**k:pytest.fail('preparation must not launch'))
    result = wc.resume_incomplete_checker(path, request_sha256=sha256(path), prepare_only=True)
    assert result['status'] == 'READY_FOR_SEALED_CHECKER_PREFLIGHT'
    assert result['candidate_message_id'] == request['candidate_message_id']
    assert not Path(request['recovery_root']).exists()


def consumed_partial_fixture(tmp_path: Path):
    request, path = partial_fixture(tmp_path)
    from slk_transport.partial_review import validate_partial_source
    basis = validate_partial_source(request)
    root = Path(request['recovery_root'])
    first = root / 'native-attempt/review-segments/segment-001'
    first.mkdir(parents=True)
    input_path = first / 'request.json'
    input_path.write_bytes(basis['segments'][0].read_bytes())
    selected = copy.deepcopy(basis['manifest']['coverage']['selected'])
    child_id = 'child-complete-reused'
    manifest = copy.deepcopy(basis['manifest'])
    manifest.update(run_id=child_id, terminal_state='complete')
    manifest['coverage'].update(completed=[selected[0]], reused=[selected[1]], failed=[])
    raw = write_json(first / 'ocrv-review.json', {
        'status': 'complete', 'session_id': child_id, 'manifest': manifest,
        'comments': [{'severity': 'MEDIUM', 'message': 'real finding'}],
        'llm': {'provider': 'dashscope-tokenplan', 'model': 'qwen3.8-max'},
        'tool_calls': {'failure': 0},
    })
    old_result = {
        'schema_version': 'slk.ocrv-d1-result/v1', 'run_id': request['run_id'],
        'cell_id': request['cell_id'], 'review_invocation_id': 'native-child-task-1',
        'verdict': 'INCOMPLETE', 'reason_codes': ['OCR_COVERAGE_INCOMPLETE'],
        'findings': json.loads(raw.read_text())['comments'], 'evidence': [],
        'request_sha256': sha256(input_path),
        'review': {'status': 'complete', 'provider': 'dashscope-tokenplan',
                   'model': 'qwen3.8-max', 'session_id': child_id, 'exit_code': 0},
        'artifacts': {'raw_review': str(raw), 'stdout': str(first / 'ocrv.stdout.txt'),
                      'stderr': str(first / 'ocrv.stderr.txt'), 'background': request['background_path']},
    }
    write_json(first / 'result.json', old_result)
    (first / 'ocrv.stdout.txt').write_text('', encoding='utf-8')
    (first / 'ocrv.stderr.txt').write_text('native completed\n', encoding='utf-8')
    from slk_transport.native_activity import make_native_start
    import os
    start = make_native_start(adapter='ocrv-checker', run_id=request['run_id'], cell_id=request['cell_id'],
        message_id=request['candidate_message_id'], request_sha256=request['payload_sha256'],
        native_request_sha256=sha256(input_path), native_task_kind='ocrv-review',
        native_task_id='native-child-task-1', native_task_status='RUNNING', pid=os.getpid())
    write_json(first / 'started.json', start)
    write_json(root / 'native-attempt/started.json', start)
    write_json(first / 'native-activity.json', {
        'schema_version': 'slk.native-task-activity/v1', 'adapter': 'ocrv-checker',
        'run_id': request['run_id'], 'cell_id': request['cell_id'],
        'message_id': request['candidate_message_id'], 'native_task_id': 'native-child-task-1',
        'status': 'COMPLETED', 'sequence': 2, 'observed_at': '2026-10-03T00:00:00Z',
        'last_event': {'kind': 'OCRV_PROCESS_EXITED', 'sequence': 2, 'exit_code': 0},
        'waiting_on': None,
    })
    child_record = Path(request['ocrv_session']['session_record_path']).parent / f'{child_id}.jsonl'
    lineage = {'type': 'resume_lineage', 'schema_version': 'ocr.resume-lineage/v1',
        'parent_run_id': basis['manifest']['run_id'], 'run_id': child_id,
        'source_provider': 'dashscope-tokenplan', 'source_model': 'qwen3.8-max',
        'target_provider': 'dashscope-tokenplan', 'target_model': 'qwen3.8-max'}
    child_record.write_text('\n'.join(json.dumps(row) for row in [lineage,
        {'type': 'session_end', 'sessionId': child_id, 'run_manifest': manifest}]) + '\n', encoding='utf-8')
    request_sha = sha256(path)
    write_json(root.parent / 'partial-consumed.json', {
        'recovery_invocation_id': request['recovery_invocation_id'], 'request_sha256': request_sha})
    (root / 'resume-consumed.json').write_text(request_sha + '\n', encoding='ascii')
    return request, path, basis, child_record


def later_partial_fixture(tmp_path: Path):
    request, path, basis, child_record = consumed_partial_fixture(tmp_path)
    root = Path(request['recovery_root'])
    attempt = root / 'native-attempt'
    first = attempt / 'review-segments/segment-001'
    correction = attempt / 'review-corrections/segment-001'
    correction.mkdir(parents=True)
    first_result = json.loads((first / 'result.json').read_text())
    corrected = {**first_result, 'verdict': 'FAIL',
                 'reason_codes': ['OCR_BLOCKING_FINDINGS_PRESENT']}
    write_json(correction / 'result.json', corrected)
    (correction / 'native-session.jsonl').write_bytes(child_record.read_bytes())
    write_json(correction / 'correction.json', {
        'schema_version': 'slk.ocrv-normalization-correction/v1',
        'cause': 'COMPLETED_REUSED_COVERAGE_WAS_OMITTED',
        'original_result_sha256': sha256(first / 'result.json'),
        'raw_review_sha256': sha256(first / 'ocrv-review.json'),
        'corrected_result_sha256': sha256(correction / 'result.json'),
        'native_session_sha256': sha256(correction / 'native-session.jsonl'),
    })
    write_json(root / 'continue-consumed.json', {
        'request_sha256': sha256(path),
        'existing_native_task_id': first_result['review_invocation_id'],
    })
    second = attempt / 'review-segments/segment-002'
    second.mkdir(parents=True)
    (second / 'request.json').write_bytes(basis['segments'][1].read_bytes())
    (second / 'd1-background.md').write_text('frozen segment 2 background\n', encoding='utf-8')
    segment_request = json.loads((second / 'request.json').read_text())
    selected = [
        {'item_id': 'item-c', 'path': segment_request['review_scope']['include_paths'][0],
         'fingerprint': 'c' * 64},
        {'item_id': 'item-d', 'path': segment_request['review_scope']['include_paths'][1],
         'fingerprint': 'd' * 64},
    ]
    session_id = 'segment-2-partial'
    manifest = copy.deepcopy(basis['manifest'])
    manifest.update(run_id=session_id, terminal_state='partial')
    manifest['input']['source_artifact_sha256'] = 'f' * 64
    manifest['coverage'].update(
        selected=selected, completed=[selected[1]], reused=[],
        failed=[{**selected[0], 'classification': 'budget',
                 'reason': 'reached the aggregate token budget before finishing'}], waived=[])
    findings = [
        {'severity': 'high', 'message': 'preserved database finding'},
        {'severity': 'low', 'message': 'preserved observation'},
    ]
    raw = write_json(second / 'ocrv-review.json', {
        'status': 'partial', 'session_id': session_id, 'manifest': manifest,
        'comments': findings, 'llm': {'provider': 'dashscope-tokenplan', 'model': 'qwen3.8-max'},
        'tool_calls': {'failure': 0},
    })
    result = write_json(second / 'result.json', {
        'schema_version': 'slk.ocrv-d1-result/v1', 'run_id': request['run_id'],
        'cell_id': request['cell_id'], 'review_invocation_id': 'segment-2-task',
        'verdict': 'INCOMPLETE',
        'reason_codes': ['OCR_STATUS_NOT_COMPLETE', 'OCR_COVERAGE_INCOMPLETE'],
        'findings': findings, 'evidence': [], 'request_sha256': sha256(second / 'request.json'),
        'review': {'status': 'partial', 'provider': 'dashscope-tokenplan',
                   'model': 'qwen3.8-max', 'session_id': session_id, 'exit_code': 0},
        'artifacts': {'raw_review': str(raw), 'background': str(second / 'd1-background.md'),
                      'stdout': str(second / 'ocrv.stdout.txt'), 'stderr': str(second / 'ocrv.stderr.txt')},
    })
    (second / 'ocrv.stdout.txt').write_text('', encoding='utf-8')
    (second / 'ocrv.stderr.txt').write_text('budget partial\n', encoding='utf-8')
    from slk_transport.native_activity import make_native_start
    import os
    write_json(second / 'started.json', make_native_start(
        adapter='ocrv-checker', run_id=request['run_id'], cell_id=request['cell_id'],
        message_id=request['candidate_message_id'], request_sha256=request['payload_sha256'],
        native_request_sha256=sha256(second / 'request.json'), native_task_kind='ocrv-review',
        native_task_id='segment-2-task', native_task_status='RUNNING', pid=os.getpid()))
    write_json(second / 'native-activity.json', {
        'schema_version': 'slk.native-task-activity/v1', 'adapter': 'ocrv-checker',
        'run_id': request['run_id'], 'cell_id': request['cell_id'],
        'message_id': request['candidate_message_id'], 'native_task_id': 'segment-2-task',
        'status': 'COMPLETED', 'sequence': 2, 'observed_at': '2026-10-03T00:00:00Z',
        'last_event': {'kind': 'OCRV_PROCESS_EXITED', 'sequence': 2, 'exit_code': 0},
        'waiting_on': None,
    })
    session_path = Path(request['ocrv_session']['session_record_path']).parent / f'{session_id}.jsonl'
    session_path.write_text('\n'.join(json.dumps(row) for row in [
        {'type': 'review_item_failed', 'sessionId': session_id,
         'filePath': selected[0]['path'], 'fingerprint': selected[0]['fingerprint']},
        {'type': 'review_item_done', 'sessionId': session_id,
         'filePath': selected[1]['path'], 'fingerprint': selected[1]['fingerprint'],
         'comments': findings},
        {'type': 'session_end', 'sessionId': session_id, 'run_manifest': manifest},
    ]) + '\n', encoding='utf-8')
    return request, path, basis, second, result, session_path


def test_later_partial_prepare_only_accepts_exact_real_shape_without_launch(tmp_path, monkeypatch):
    from slk_transport import worker_completion as wc
    from test_incomplete_checker_resume import dead_activity
    request, path, _basis, _second, _result, _session = later_partial_fixture(tmp_path)
    monkeypatch.setattr(wc, 'inspect_native_activity', dead_activity)
    monkeypatch.setattr(wc, '_default_load_current_projection',
                        lambda *a: json.loads(Path(request['runtime_projection_path']).read_text()))
    monkeypatch.setattr(wc, '_run_sealed_checker_terminal',
                        lambda *a, **k: pytest.fail('prepare-only must not launch'))

    result = wc.resume_consumed_partial_checker(path, request_sha256=sha256(path), prepare_only=True)

    assert result['status'] == 'READY_TO_RESUME_PARTIAL_SEGMENT_2'
    assert result['partial_session_id'] == 'segment-2-partial'
    assert result['failed_paths'] == ['src/c.py']
    assert result['reused_paths'] == ['src/d.py']
    assert not (Path(request['recovery_root']) / 'resume-partial-segment-002').exists()


@pytest.mark.parametrize('mutation', ['continue-marker', 'segment-request', 'session', 'segment-3', 'one-shot'])
def test_later_partial_admission_rejects_drift_or_second_use(tmp_path, monkeypatch, mutation):
    from slk_transport import worker_completion as wc
    from test_incomplete_checker_resume import dead_activity
    request, path, _basis, second, _result, session = later_partial_fixture(tmp_path)
    root = Path(request['recovery_root'])
    if mutation == 'continue-marker':
        write_json(root / 'continue-consumed.json', {'request_sha256': '0' * 64,
                                                     'existing_native_task_id': 'segment-1-task'})
    elif mutation == 'segment-request':
        (second / 'request.json').write_text('{}\n', encoding='utf-8')
    elif mutation == 'session':
        session.write_text('{}\n', encoding='utf-8')
    elif mutation == 'segment-3':
        (root / 'native-attempt/review-segments/segment-003').mkdir(parents=True)
    else:
        (root / 'resume-partial-segment-002').mkdir()
    monkeypatch.setattr(wc, 'inspect_native_activity', dead_activity)
    monkeypatch.setattr(wc, '_run_sealed_checker_terminal',
                        lambda *a, **k: pytest.fail('invalid evidence must not launch'))
    with pytest.raises(wc.CompletionError):
        wc.resume_consumed_partial_checker(path, request_sha256=sha256(path))


@pytest.mark.parametrize('outcome', ['complete', 'partial'])
def test_later_partial_resume_is_one_shot_preserves_findings_and_never_starts_segment_3(
    tmp_path, monkeypatch, capsys, outcome
):
    import importlib
    import os
    import subprocess
    from slk_transport import worker_completion as wc
    from slk_transport.native_activity import make_native_start
    from slk_transport.partial_review import read
    from test_incomplete_checker_resume import dead_activity
    request, path, _basis, second, _result, _session = later_partial_fixture(tmp_path)
    root = Path(__file__).resolve().parents[2]
    monkeypatch.syspath_prepend(str(root / 'integrations/ocrv'))
    recovery = importlib.import_module('slk_checker_recovery')
    monkeypatch.setattr(wc, 'inspect_native_activity', dead_activity)
    for key, value in {'SLK_OCRV_RECOVERY_ROLE_INSTANCE_ID': request['checker_role_instance_id'],
        'SLK_OCRV_RECOVERY_ENDPOINT_VERSION': str(request['checker_endpoint_version']),
        'SLK_OCRV_RECOVERY_INVOCATION_ID': request['recovery_invocation_id']}.items():
        monkeypatch.setenv(key, value)
    authentication = lambda *a: {'status':'authenticated', 'role':'checker',
        'role_instance_id':request['checker_role_instance_id'], 'runtime_revision':request['runtime_revision']}
    monkeypatch.setattr(wc, '_default_checker_authenticate', authentication)
    launched, records = [], {}

    def native_run(input_path, output_path, **kwargs):
        launched.append((read(input_path), kwargs))
        old_raw = read(second / 'ocrv-review.json')
        manifest = copy.deepcopy(old_raw['manifest'])
        session_id = f'segment-2-{outcome}-child'
        manifest.update(run_id=session_id, terminal_state=outcome)
        selected = manifest['coverage']['selected']
        if outcome == 'complete':
            manifest['coverage'].update(completed=[selected[0]], reused=[selected[1]], failed=[], waived=[])
            status, verdict, reasons, adapter_code = 'complete', 'FAIL', ['OCR_BLOCKING_FINDINGS_PRESENT'], 2
        else:
            manifest['coverage'].update(completed=[], reused=[selected[1]],
                failed=[{**selected[0], 'classification':'budget',
                         'reason':'reached the aggregate token budget before finishing'}], waived=[])
            status, verdict, reasons, adapter_code = 'partial', 'INCOMPLETE', [
                'OCR_STATUS_NOT_COMPLETE','OCR_COVERAGE_INCOMPLETE'], 3
        raw_path = write_json(output_path.parent / 'ocrv-review.json', {
            'status':status, 'session_id':session_id, 'manifest':manifest,
            'comments':old_raw['comments'],
            'llm':{'provider':'dashscope-tokenplan','model':'qwen3.8-max'},
            'tool_calls':{'failure':0}})
        write_json(output_path, {'schema_version':'slk.ocrv-d1-result/v1',
            'run_id':request['run_id'],'cell_id':request['cell_id'],
            'review_invocation_id':kwargs['invocation_override'],'verdict':verdict,
            'reason_codes':reasons,'findings':old_raw['comments'],'evidence':[],
            'request_sha256':sha256(input_path),
            'review':{'status':status,'provider':'dashscope-tokenplan','model':'qwen3.8-max',
                      'session_id':session_id,'exit_code':0},
            'artifacts':{'raw_review':str(raw_path),'background':str(kwargs['background_override']),
                         'stdout':str(output_path.parent / 'ocrv.stdout.txt'),
                         'stderr':str(output_path.parent / 'ocrv.stderr.txt')}})
        write_json(Path(os.environ['SLK_NATIVE_START_RECEIPT']), make_native_start(
            adapter='ocrv-checker',run_id=request['run_id'],cell_id=request['cell_id'],
            message_id=request['candidate_message_id'],request_sha256=request['payload_sha256'],
            native_request_sha256=sha256(input_path),native_task_kind='ocrv-review',
            native_task_id=kwargs['invocation_override'],native_task_status='RUNNING',pid=os.getpid()))
        write_json(output_path.parent / 'native-activity.json', {
            'schema_version':'slk.native-task-activity/v1','adapter':'ocrv-checker',
            'run_id':request['run_id'],'cell_id':request['cell_id'],'message_id':request['candidate_message_id'],
            'native_task_id':kwargs['invocation_override'],'status':'COMPLETED','sequence':1,
            'observed_at':'2026-10-03T00:00:00Z',
            'last_event':{'kind':'OCRV_PROCESS_EXITED','sequence':1,'exit_code':0},'waiting_on':None})
        (output_path.parent / 'ocrv.stdout.txt').write_text('', encoding='utf-8')
        (output_path.parent / 'ocrv.stderr.txt').write_text('bounded resume\n', encoding='utf-8')
        native_path = Path(request['ocrv_session']['session_record_path']).parent / f'{session_id}.jsonl'
        lineage = {'type':'resume_lineage','schema_version':'ocr.resume-lineage/v1',
            'parent_run_id':'segment-2-partial','run_id':session_id,
            'source_provider':'dashscope-tokenplan','source_model':'qwen3.8-max',
            'target_provider':'dashscope-tokenplan','target_model':'qwen3.8-max'}
        native_path.write_text('\n'.join(json.dumps(row) for row in [lineage,
            {'type':'session_end','sessionId':session_id,'run_manifest':manifest}])+'\n', encoding='utf-8')
        records[session_id] = native_path
        return adapter_code

    monkeypatch.setattr(recovery.checker_adapter, 'run', native_run)
    monkeypatch.setattr(recovery, '_run_ocrv_json',
        lambda args: {'summary':{'file_path':str(records[args[-1]])},'items':[]})
    writes = []
    monkeypatch.setattr(wc, 'unprotect_dpapi_hex', lambda *a:'test-only')
    monkeypatch.setattr(wc, '_run_json_command', lambda command, args, **kwargs:
        writes.append(read(Path(args[args.index('--request')+1]))) or {'status':'recorded','run_id':request['run_id']})

    def terminal_host(args, **kwargs):
        terminal_path = Path(args[args.index('--request')+1])
        result = wc.execute_committed_checker_terminal(
            read(terminal_path), request_sha256=sha256(terminal_path), authenticate_checker=authentication)
        return subprocess.CompletedProcess(args, 0, json.dumps(result).encode(), b'')

    monkeypatch.setattr(recovery.subprocess, 'run', terminal_host)
    if outcome == 'partial':
        with pytest.raises(ValueError, match='one-shot is consumed'):
            recovery._resume_partial(request, path, request['transport_command'], consumed=True, resume_later=True)
        receipt = Path(request['recovery_root']) / 'resume-partial-segment-002/incomplete.json'
        assert read(receipt)['status'] == 'INCOMPLETE'
        assert not (Path(request['recovery_root']) / 'native-attempt/review-corrections/segment-002').exists()
        assert not (Path(request['recovery_root']) / 'native-attempt/ocrv-aggregate.json').exists()
        assert writes == []
    else:
        assert recovery._resume_partial(
            request, path, request['transport_command'], consumed=True, resume_later=True) == 0
        capsys.readouterr()
        assert read(Path(request['recovery_root']) / 'resume-partial-segment-002/complete.json')['status'] == 'COMPLETE'
        assert read(Path(request['recovery_root']) / 'native-attempt/ocrv-aggregate.json')['completed_segment_count'] == 2
        assert [item['event_type'] for item in writes] == ['D1_FAILED']
        from slk_transport.partial_review import validate_partial_terminal
        committed = read(Path(request['recovery_root']) / 'committed-terminal.json')
        validated = validate_partial_terminal(committed, recorded_d1=writes[0])
        assert Path(validated['activation']['native_attempt_path']) == Path(request['recovery_root']) / 'native-attempt'
        corrupted = {**writes[0], 'event_id': 'different-event'}
        with pytest.raises(ValueError):
            validate_partial_terminal(committed, recorded_d1=corrupted)
        write_json(Path(request['recovery_root']) / 'native-attempt/extra.json', {})
        with pytest.raises(ValueError):
            validate_partial_terminal(committed, recorded_d1=writes[0])
    assert len(launched) == 1
    assert launched[0][1]['resume_session'] == 'segment-2-partial'
    assert launched[0][0]['capacity']['max_tokens_budget'] == 500000
    assert not (Path(request['recovery_root']) / 'native-attempt/review-segments/segment-003').exists()


@pytest.mark.parametrize('mutation', ['drop-finding', 'recheck-completed'])
def test_completed_later_resume_rejects_lost_finding_or_duplicate_review(tmp_path, mutation):
    from slk_transport.partial_review import (
        validate_completed_segment_resume, validate_consumed_partial_resume_attempt)
    request, path, _basis, _second, _result, _session = later_partial_fixture(tmp_path)
    partial = validate_consumed_partial_resume_attempt(request, sha256(path))
    raw = copy.deepcopy(partial['partial_raw'])
    raw.update(status='complete', session_id='segment-2-child')
    raw['manifest'].update(run_id='segment-2-child', terminal_state='complete')
    selected = raw['manifest']['coverage']['selected']
    raw['manifest']['coverage'].update(completed=[selected[0]], reused=[selected[1]], failed=[], waived=[])
    lineage = {'schema_version':'ocr.resume-lineage/v1','parent_run_id':'segment-2-partial',
        'run_id':'segment-2-child','source_provider':'dashscope-tokenplan','source_model':'qwen3.8-max',
        'target_provider':'dashscope-tokenplan','target_model':'qwen3.8-max'}
    if mutation == 'drop-finding':
        raw['comments'] = raw['comments'][1:]
    else:
        raw['manifest']['coverage'].update(completed=selected, reused=[])
    with pytest.raises(ValueError):
        validate_completed_segment_resume(partial, raw, lineage)


def test_consumed_partial_prepare_only_accepts_exact_completed_native_child_without_launch(tmp_path, monkeypatch):
    from slk_transport import worker_completion as wc
    from test_incomplete_checker_resume import dead_activity
    request, path, _basis, _child = consumed_partial_fixture(tmp_path)
    monkeypatch.setattr(wc, 'inspect_native_activity', dead_activity)
    monkeypatch.setattr(wc, '_run_sealed_checker_terminal', lambda *a, **k: pytest.fail('preflight must not launch'))
    current = copy.deepcopy(json.loads(Path(request['runtime_projection_path']).read_text()))
    current['runtime_snapshot']['runtime_revision'] = request['runtime_revision'] + 2
    monkeypatch.setattr(wc, '_default_load_current_projection', lambda *a: current)
    checked = []
    monkeypatch.setattr(wc, '_rebind_overwatcher_only_committed_boundary',
        lambda _request, _frozen, _current, revision: checked.append(revision) or revision)

    result = wc.continue_consumed_partial_checker(path, request_sha256=sha256(path), prepare_only=True)

    assert result['status'] == 'READY_TO_CONSUME_COMPLETED_SEGMENT_1'
    assert result['completed_segment_count'] == 1
    assert result['current_runtime_revision'] == request['runtime_revision'] + 2
    assert checked == [request['runtime_revision'] + 2]
    assert not (Path(request['recovery_root']) / 'continue-consumed.json').exists()


def test_consumed_partial_sealed_start_rebinds_before_paid_work(tmp_path, monkeypatch):
    import importlib
    import os
    from slk_transport import partial_review
    from slk_transport import worker_completion as wc
    from test_incomplete_checker_resume import dead_activity

    request, path, _basis, _child = consumed_partial_fixture(tmp_path)
    root = Path(__file__).resolve().parents[2]
    monkeypatch.syspath_prepend(str(root / 'integrations/ocrv'))
    recovery = importlib.import_module('slk_checker_recovery')
    monkeypatch.setattr(wc, 'inspect_native_activity', dead_activity)
    for key, value in {
        'SLK_OCRV_RECOVERY_ROLE_INSTANCE_ID': request['checker_role_instance_id'],
        'SLK_OCRV_RECOVERY_ENDPOINT_VERSION': str(request['checker_endpoint_version']),
        'SLK_OCRV_RECOVERY_INVOCATION_ID': request['recovery_invocation_id'],
    }.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(wc, '_default_checker_authenticate', lambda *a: {
        'status': 'authenticated', 'role': 'checker',
        'role_instance_id': request['checker_role_instance_id'],
        'runtime_revision': request['runtime_revision'] + 2,
    })
    current = copy.deepcopy(json.loads(Path(request['runtime_projection_path']).read_text()))
    current['runtime_snapshot']['runtime_revision'] = request['runtime_revision'] + 2
    monkeypatch.setattr(wc, '_default_load_current_projection', lambda *a: current)
    checked = []
    monkeypatch.setattr(wc, '_rebind_overwatcher_only_committed_boundary',
        lambda _request, _frozen, _current, revision: checked.append(revision) or revision)

    class StopBeforePaidWork(RuntimeError):
        pass

    monkeypatch.setattr(partial_review, 'validate_consumed_partial_attempt',
        lambda *a: (_ for _ in ()).throw(StopBeforePaidWork()))
    monkeypatch.setattr(recovery.checker_adapter, 'run',
        lambda *a, **k: pytest.fail('paid work must not start before current-boundary validation'))

    with pytest.raises(StopBeforePaidWork):
        recovery._resume_partial(request, path, request['transport_command'], consumed=True)

    assert checked == [request['runtime_revision'] + 2]
    assert not (Path(request['recovery_root']) / 'continue-consumed.json').exists()


@pytest.mark.parametrize('blocking_remaining', [False, True])
def test_consumed_partial_executes_only_unstarted_segments_and_preserves_old_result(
    tmp_path, monkeypatch, capsys, blocking_remaining
):
    import importlib
    import os
    import subprocess
    from slk_transport import worker_completion as wc
    from slk_transport.native_activity import make_native_start
    from slk_transport.partial_review import read
    from test_incomplete_checker_resume import dead_activity
    request, path, basis, _existing_child = consumed_partial_fixture(tmp_path)
    root = Path(__file__).resolve().parents[2]
    monkeypatch.syspath_prepend(str(root / 'integrations/ocrv'))
    recovery = importlib.import_module('slk_checker_recovery')
    monkeypatch.setattr(wc, 'inspect_native_activity', dead_activity)
    for key, value in {'SLK_OCRV_RECOVERY_ROLE_INSTANCE_ID': request['checker_role_instance_id'],
        'SLK_OCRV_RECOVERY_ENDPOINT_VERSION': str(request['checker_endpoint_version']),
        'SLK_OCRV_RECOVERY_INVOCATION_ID': request['recovery_invocation_id']}.items():
        monkeypatch.setenv(key, value)
    authentication = lambda *a: {'status': 'authenticated', 'role': 'checker',
        'role_instance_id': request['checker_role_instance_id'], 'runtime_revision': request['runtime_revision']}
    monkeypatch.setattr(wc, '_default_checker_authenticate', authentication)
    launched, native_records = [], {}

    def native_run(input_path, output_path, **kwargs):
        launched.append((read(input_path), kwargs))
        value = read(input_path)
        session_id = f'remaining-child-{len(launched)}'
        selected = [{'item_id': p, 'path': p, 'fingerprint': str(len(launched)) * 64}
                    for p in value['review_scope']['include_paths']]
        manifest = copy.deepcopy(basis['manifest'])
        manifest.update(run_id=session_id, terminal_state='complete')
        manifest['coverage'].update(selected=selected, completed=selected, reused=[], failed=[])
        comments = ([{'severity': 'HIGH', 'message': 'stop remaining review'}]
                    if blocking_remaining and len(launched) == 1 else [])
        verdict = 'FAIL' if comments else 'PASS'
        raw_path = write_json(output_path.parent / 'ocrv-review.json', {'status': 'complete',
            'session_id': session_id, 'manifest': manifest, 'comments': comments,
            'llm': {'provider': 'dashscope-tokenplan', 'model': 'qwen3.8-max'},
            'tool_calls': {'failure': 0}})
        write_json(output_path, {'schema_version': 'slk.ocrv-d1-result/v1', 'run_id': request['run_id'],
            'cell_id': request['cell_id'], 'review_invocation_id': kwargs['invocation_override'],
            'verdict': verdict, 'reason_codes': ['OCR_BLOCKING_FINDINGS_PRESENT'] if comments else ['OCR_COMPLETE_ZERO_FINDINGS'],
            'findings': comments,
            'evidence': [], 'request_sha256': sha256(input_path),
            'review': {'status': 'complete', 'provider': 'dashscope-tokenplan', 'model': 'qwen3.8-max',
                       'session_id': session_id, 'exit_code': 0}, 'artifacts': {'raw_review': str(raw_path)}})
        write_json(Path(os.environ['SLK_NATIVE_START_RECEIPT']), make_native_start(adapter='ocrv-checker',
            run_id=request['run_id'], cell_id=request['cell_id'], message_id=request['candidate_message_id'],
            request_sha256=request['payload_sha256'], native_request_sha256=sha256(input_path),
            native_task_kind='ocrv-review', native_task_id=kwargs['invocation_override'],
            native_task_status='RUNNING', pid=os.getpid()))
        record = Path(request['ocrv_session']['session_record_path']).parent / f'{session_id}.jsonl'
        record.write_text(json.dumps({'type': 'session_end', 'sessionId': session_id,
                                      'run_manifest': manifest}) + '\n', encoding='utf-8')
        native_records[session_id] = record
        return 2 if comments else 0

    monkeypatch.setattr(recovery.checker_adapter, 'run', native_run)
    monkeypatch.setattr(recovery, '_run_ocrv_json',
        lambda args: {'summary': {'file_path': str(native_records[args[-1]])}, 'items': []})
    writes = []
    monkeypatch.setattr(wc, 'unprotect_dpapi_hex', lambda *a: 'test-only')
    monkeypatch.setattr(wc, '_run_json_command', lambda command, args, **kwargs:
        writes.append(read(Path(args[args.index('--request') + 1]))) or {'status': 'recorded', 'run_id': request['run_id']})

    def terminal_host(args, **kwargs):
        terminal_path = Path(args[args.index('--request') + 1])
        result = wc.execute_committed_checker_terminal(read(terminal_path), request_sha256=sha256(terminal_path),
                                                       authenticate_checker=authentication)
        return subprocess.CompletedProcess(args, 0, json.dumps(result).encode(), b'')

    monkeypatch.setattr(recovery.subprocess, 'run', terminal_host)
    old_result = Path(request['recovery_root']) / 'native-attempt/review-segments/segment-001/result.json'
    old_bytes = old_result.read_bytes()

    assert recovery._resume_partial(request, path, request['transport_command'], consumed=True) == 0
    capsys.readouterr()
    assert len(launched) == (1 if blocking_remaining else 2)
    assert all(item[1]['resume_session'] is None for item in launched)
    assert old_result.read_bytes() == old_bytes
    correction = Path(request['recovery_root']) / 'native-attempt/review-corrections/segment-001/result.json'
    assert read(correction)['verdict'] == 'FAIL'
    assert [item['event_type'] for item in writes] == ['D1_FAILED']


@pytest.mark.parametrize('mutation', ['marker', 'old-result', 'child-record', 'segment-2', 'continued'])
def test_consumed_partial_drift_is_rejected_before_sealed_launch(tmp_path, monkeypatch, mutation):
    from slk_transport import worker_completion as wc
    from slk_transport.partial_review import read
    from test_incomplete_checker_resume import dead_activity
    request, path, _basis, child = consumed_partial_fixture(tmp_path)
    root = Path(request['recovery_root'])
    if mutation == 'marker':
        write_json(root.parent / 'partial-consumed.json', {
            'recovery_invocation_id': request['recovery_invocation_id'], 'request_sha256': '0' * 64})
    elif mutation == 'old-result':
        old = read(root / 'native-attempt/review-segments/segment-001/result.json')
        old['reason_codes'] = ['OTHER']
        write_json(root / 'native-attempt/review-segments/segment-001/result.json', old)
    elif mutation == 'child-record':
        child.write_text('{}\n', encoding='utf-8')
    elif mutation == 'segment-2':
        (root / 'native-attempt/review-segments/segment-002').mkdir(parents=True)
    else:
        write_json(root / 'continue-consumed.json', {'request_sha256': sha256(path)})
    monkeypatch.setattr(wc, 'inspect_native_activity', dead_activity)
    monkeypatch.setattr(wc, '_run_sealed_checker_terminal', lambda *a, **k: pytest.fail('drift must not launch'))
    with pytest.raises(wc.CompletionError):
        wc.continue_consumed_partial_checker(path, request_sha256=sha256(path))


@pytest.mark.parametrize('mutation', ['candidate', 'checkpoint', 'old-terminal', 'scope', 'consumed'])
def test_partial_source_drift_is_rejected_before_any_native_launch(tmp_path, mutation):
    from slk_transport.partial_review import validate_partial_source
    request, _ = partial_fixture(tmp_path)
    if mutation == 'candidate': request['candidate_commit'] = 'f'*40
    elif mutation == 'checkpoint': Path(request['ocrv_session']['session_record_path']).write_text('{}\n')
    elif mutation == 'old-terminal': write_json(Path(request['native_attempt_path']) / 'completed.json', {})
    elif mutation == 'scope': request['partial_review']['planned_segment_count'] = 4
    else: write_json(Path(request['recovery_root']) / 'resume-consumed.json', {})
    with pytest.raises(ValueError): validate_partial_source(request)


def test_native_child_lineage_must_reuse_parent_completed_fingerprint(tmp_path):
    from slk_transport.partial_review import validate_resumed_raw
    request, _ = partial_fixture(tmp_path)
    from slk_transport.partial_review import validate_partial_source
    basis = validate_partial_source(request)
    child = copy.deepcopy(basis['raw'])
    child.update(status='complete', session_id='child-session')
    child['manifest'].update(run_id='child-session', terminal_state='complete')
    coverage = child['manifest']['coverage']
    coverage.update(completed=[coverage['selected'][0]], reused=[coverage['selected'][1]], failed=[])
    lineage = {'schema_version': 'ocr.resume-lineage/v1', 'parent_run_id': 'ocrv-session-1',
               'run_id': 'child-session', 'source_provider': 'dashscope-tokenplan', 'source_model': 'qwen3.8-max',
               'target_provider': 'dashscope-tokenplan', 'target_model': 'qwen3.8-max'}
    validate_resumed_raw(basis, child, lineage)
    child['manifest']['coverage']['reused'] = []
    with pytest.raises(ValueError): validate_resumed_raw(basis, child, lineage)


@pytest.mark.parametrize('variant', ['normal', 'missing-file-path', 'false-pass'])
def test_sealed_partial_continuation_uses_three_frozen_segments_and_one_correcting_d1(tmp_path, monkeypatch, capsys, variant):
    import importlib
    import os
    import subprocess
    from slk_transport import worker_completion as wc
    from slk_transport.native_activity import make_native_start
    from slk_transport.partial_review import read, validate_partial_source
    from test_incomplete_checker_resume import dead_activity
    request, path = partial_fixture(tmp_path)
    basis = validate_partial_source(request)
    root = Path(__file__).resolve().parents[2]
    monkeypatch.syspath_prepend(str(root / 'integrations/ocrv'))
    recovery = importlib.import_module('slk_checker_recovery')
    monkeypatch.setattr(wc, 'inspect_native_activity', dead_activity)
    for key, value in {'SLK_OCRV_RECOVERY_ROLE_INSTANCE_ID': request['checker_role_instance_id'],
        'SLK_OCRV_RECOVERY_ENDPOINT_VERSION': str(request['checker_endpoint_version']),
        'SLK_OCRV_RECOVERY_INVOCATION_ID': request['recovery_invocation_id']}.items(): monkeypatch.setenv(key, value)
    authentication = lambda *a: {'status':'authenticated', 'role':'checker',
        'role_instance_id':request['checker_role_instance_id'], 'runtime_revision':request['runtime_revision']}
    monkeypatch.setattr(wc, '_default_checker_authenticate', authentication)
    native_records = {}
    def native_json(args):
        if args[:2] == ['session','list']: return [request['ocrv_session']]
        if args[-1] == request['ocrv_session']['session_id']:
            return {'summary': {'session_id':args[-1], 'run_manifest':basis['manifest'],
                    **({} if variant == 'missing-file-path' else {'file_path':request['ocrv_session']['session_record_path']})},
                    'items':[{'fingerprint':'b'*64, 'type':'done'}]}
        return {'summary': {'file_path':str(native_records[args[-1]])}, 'items':[]}
    monkeypatch.setattr(recovery, '_run_ocrv_json', native_json)
    launched = []
    def native_run(input_path, output_path, **kwargs):
        launched.append((read(input_path), kwargs))
        n = len(launched)
        value = read(input_path)
        session_id = f'child-{n}'
        manifest = copy.deepcopy(basis['manifest'])
        manifest.update(run_id=session_id, terminal_state='complete')
        if n == 1:
            selected = manifest['coverage']['selected']
            manifest['coverage'].update(completed=[selected[0]], reused=[selected[1]], failed=[])
        else:
            selected = [{'item_id':p, 'path':p, 'fingerprint':str(n)*64} for p in value['review_scope']['include_paths']]
            manifest['coverage'].update(selected=selected, completed=selected, reused=[], failed=[])
        raw_path = write_json(output_path.parent / 'ocrv-review.json', {'status':'complete',
            'session_id':session_id, 'manifest':manifest, 'comments':[{'severity':'MEDIUM'}] if variant == 'false-pass' else [],
            'llm':{'provider':'dashscope-tokenplan','model':'qwen3.8-max'},'tool_calls':{'failure':0}})
        write_json(output_path, {'schema_version':'slk.ocrv-d1-result/v1', 'run_id':request['run_id'],
            'cell_id':request['cell_id'], 'review_invocation_id':kwargs['invocation_override'], 'verdict':'PASS',
            'reason_codes':[], 'findings':[], 'evidence':[], 'request_sha256':sha256(input_path),
            'review': {'status':'complete', 'provider':'dashscope-tokenplan', 'model':'qwen3.8-max',
                'session_id':session_id, 'exit_code':0}, 'artifacts': {'raw_review':str(raw_path)}})
        write_json(Path(os.environ['SLK_NATIVE_START_RECEIPT']), make_native_start(adapter='ocrv-checker',
            run_id=request['run_id'],cell_id=request['cell_id'],message_id=request['candidate_message_id'],
            request_sha256=request['payload_sha256'], native_request_sha256=sha256(input_path),
            native_task_kind='ocrv-review',native_task_id=kwargs['invocation_override'],native_task_status='RUNNING',pid=os.getpid()))
        native_record = Path(request['ocrv_session']['session_record_path']).parent / f'{session_id}.jsonl'
        lineage = {'type':'resume_lineage', 'schema_version':'ocr.resume-lineage/v1','parent_run_id':'ocrv-session-1',
            'run_id':session_id,'source_provider':'dashscope-tokenplan','source_model':'qwen3.8-max',
            'target_provider':'dashscope-tokenplan','target_model':'qwen3.8-max'}
        native_record.write_text('\n'.join(json.dumps(row) for row in [
            {'type':'session_start', 'sessionId':session_id},
            *([lineage] if n == 1 else []), {'type':'session_end', 'sessionId':session_id,'run_manifest':manifest}])+'\n')
        native_records[session_id] = native_record
        return 0
    monkeypatch.setattr(recovery.checker_adapter, 'run', native_run)
    writes = []
    monkeypatch.setattr(wc, 'unprotect_dpapi_hex', lambda *a:'test-only')
    def state_write(command, args, **kwargs):
        writes.append(read(Path(args[args.index('--request')+1])))
        return {'status':'recorded','run_id':request['run_id']}
    monkeypatch.setattr(wc, '_run_json_command', state_write)
    def terminal_host(args, **kwargs):
        terminal_path = Path(args[args.index('--request')+1])
        result = wc.execute_committed_checker_terminal(read(terminal_path), request_sha256=sha256(terminal_path),
                                                       authenticate_checker=authentication)
        return subprocess.CompletedProcess(args, 0, json.dumps(result).encode(), b'')
    monkeypatch.setattr(recovery.subprocess, 'run', terminal_host)
    original = {p:p.read_bytes() for p in basis['source'].rglob('*') if p.is_file()}
    if variant == 'missing-file-path':
        with pytest.raises(ValueError, match='reusable native parent'): recovery._resume_partial(request, path, request['transport_command'])
        assert not launched and not Path(request['recovery_root']).exists()
        return
    if variant == 'false-pass':
        with pytest.raises(wc.CompletionError): recovery._resume_partial(request, path, request['transport_command'])
        assert not writes
        return
    assert recovery._resume_partial(request, path, request['transport_command']) == 0
    capsys.readouterr()
    assert len(launched) == 3
    assert launched[0][1]['resume_session'] == 'ocrv-session-1'
    assert all(value[1]['resume_session'] is None for value in launched[1:])
    assert [value['event_type'] for value in writes] == ['D1_PASSED']
    assert writes[0]['corrects_event_id'] == 'd1-incomplete'
    assert writes[0]['attempt'] == request['attempt']
    assert all(p.read_bytes() == data for p,data in original.items())
    with pytest.raises(ValueError): validate_partial_source(request)


@pytest.mark.parametrize('field', ['candidate_commit','candidate_parent','checker_role_instance_id','runtime_revision','token_sequence', 'endpoint_version'])
def test_public_partial_gate_rejects_identity_drift_before_host(tmp_path, monkeypatch, field):
    from slk_transport import worker_completion as wc
    from test_incomplete_checker_resume import dead_activity
    request, path = partial_fixture(tmp_path)
    if field == 'endpoint_version': request['checker_endpoint_version'] += 1
    elif isinstance(request[field], int): request[field] += 1
    else: request[field] = 'f'*40
    write_json(path, request)
    monkeypatch.setattr(wc, 'inspect_native_activity', dead_activity)
    monkeypatch.setattr(wc, '_run_sealed_checker_terminal', lambda *a,**k:pytest.fail('drift must not launch'))
    with pytest.raises(wc.CompletionError): wc.resume_incomplete_checker(path, request_sha256=sha256(path))
