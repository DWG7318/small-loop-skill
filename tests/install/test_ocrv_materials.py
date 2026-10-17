"""The existing Checker bridge reads exact indexed originals, not Git substitutes."""
import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest

from test_ocrv_preflight import _fake_ocr, _request


def load(name):
    path = Path(__file__).resolve().parents[2] / 'integrations/ocrv' / name
    spec = importlib.util.spec_from_file_location(path.stem + '_materials', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def bind(tmp_path, monkeypatch, text='原始错误\n' * 3000):
    original = tmp_path / 'not-in-git.log'
    original.write_text(text, encoding='utf-8')
    receipt = tmp_path / 'native-start.received.json'
    identity = {'run_id': 'RUN-A', 'cell_id': 'CELL-001', 'message_id': 'message-A',
                'native_request_sha256': 'a' * 64}
    receipt.write_text(json.dumps({**identity, 'native_task': {'id': 'native-A'}}), encoding='utf-8')
    index = tmp_path / 'evidence-index.json'
    index.write_text(json.dumps({**identity, 'native_task_id': 'native-A', 'evidence': [{
        'path': str(original), 'sha256': hashlib.sha256(original.read_bytes()).hexdigest(),
        'bytes': original.stat().st_size}]}), encoding='utf-8')
    monkeypatch.setenv('SLK_NATIVE_START_RECEIPT', str(receipt))
    monkeypatch.setenv('SLK_CHECKER_EVIDENCE_INDEX', str(index))
    monkeypatch.setenv('SLK_CHECKER_EVIDENCE_INDEX_SHA256', hashlib.sha256(index.read_bytes()).hexdigest())
    return original, receipt, index


def test_reader_returns_exact_original_ranges_chosen_by_checker(tmp_path, monkeypatch):
    bridge = load('slk_checker_decision.py')
    original, _, _ = bind(tmp_path, monkeypatch)
    first = bridge.read_evidence(0, offset=0, limit=17)
    second = bridge.read_evidence(0, offset=first['next_offset'], limit=17)
    text = original.read_bytes().decode('utf-8')
    assert first['text'] + second['text'] == text[:34]
    assert first['sha256'] == hashlib.sha256(original.read_bytes()).hexdigest()
    assert first['eof'] is False
    assert first['path'] == str(original)


def test_reader_default_returns_entire_original_above_old_limits(tmp_path, monkeypatch):
    bridge = load('slk_checker_decision.py')
    text = '原始证据\r\n' * 3000 + '文件末尾，不能丢失'
    original, _, _ = bind(tmp_path, monkeypatch, text)
    expected = original.read_bytes().decode('utf-8')
    result = bridge.read_evidence(0)
    assert len(expected) > 8000
    assert result['text'] == expected
    assert result['next_offset'] == len(expected)
    assert result['eof'] is True


@pytest.mark.parametrize('limit', [6001, 8001, 12000, 100_000, 10**30])
def test_reader_accepts_checker_selected_length_without_ceiling(tmp_path, monkeypatch, limit):
    bridge = load('slk_checker_decision.py')
    original, _, _ = bind(tmp_path, monkeypatch)
    expected = original.read_bytes().decode('utf-8')
    result = bridge.read_evidence(0, limit=limit)
    assert result['text'] == expected[:limit]
    assert result['next_offset'] == min(limit, len(expected))
    assert result['eof'] is (limit >= len(expected))


def test_reader_without_length_returns_remaining_original_from_offset(tmp_path, monkeypatch):
    bridge = load('slk_checker_decision.py')
    original, _, _ = bind(tmp_path, monkeypatch)
    expected = original.read_bytes().decode('utf-8')
    result = bridge.read_evidence(0, offset=13)
    assert result['text'] == expected[13:]
    assert result['next_offset'] == len(expected)
    assert result['eof'] is True


def test_reader_protocol_default_returns_full_original_without_length_gate(tmp_path, monkeypatch):
    bridge = load('slk_checker_decision.py')
    original, _, _ = bind(tmp_path, monkeypatch)
    call = {'id': 1, 'method': 'tools/call', 'params': {
        'name': 'slk_read_evidence', 'arguments': {'index': 0}}}
    response = bridge.respond(call)
    assert not response['result'].get('isError')
    result = json.loads(response['result']['content'][0]['text'])
    assert result['text'] == original.read_bytes().decode('utf-8')
    assert len(result['text']) > 8000
    limit_schema = bridge.READ_TOOL['inputSchema']['properties']['limit']
    assert 'maximum' not in limit_schema
    assert 'default' not in limit_schema


@pytest.mark.parametrize('damage', ['file', 'index', 'invocation'])
def test_reader_rejects_changed_bytes_or_wrong_binding(tmp_path, monkeypatch, damage):
    bridge = load('slk_checker_decision.py')
    original, receipt, index = bind(tmp_path, monkeypatch)
    if damage == 'file':
        original.write_text('changed', encoding='utf-8')
    elif damage == 'index':
        index.write_text('{}', encoding='utf-8')
    else:
        value = json.loads(receipt.read_text(encoding='utf-8'))
        value['native_task']['id'] = 'other-native'
        receipt.write_text(json.dumps(value), encoding='utf-8')
    with pytest.raises(ValueError):
        bridge.read_evidence(0)


@pytest.mark.parametrize('arguments', [(-1, 0, 10), (1, 0, 10), (0, -1, 10),
                                       (0, 0, 0), (0, 0, -1), (0, 0, True), (0, 0, 1.5),
                                       (True, 0, 10)])
def test_reader_rejects_invalid_ranges_and_unregistered_files(tmp_path, monkeypatch, arguments):
    bridge = load('slk_checker_decision.py')
    bind(tmp_path, monkeypatch)
    with pytest.raises(ValueError):
        bridge.read_evidence(arguments[0], offset=arguments[1], limit=arguments[2])


def test_management_summary_stays_in_request_not_bootstrap_or_worker_log(tmp_path):
    adapter = load('slk_checker_adapter.py')
    request_path, _, _ = _request(tmp_path)
    request = json.loads(request_path.read_text(encoding='utf-8'))
    request['management_context'] = {'management_action': 'SUPPLY_EVIDENCE',
        'management_summary': 'Read the original missing log; retain the frozen candidate.',
        'management_evidence_refs': [request['evidence_files'][0]]}
    normalized = adapter._validate_request(request)
    background = adapter._background(normalized)
    assert normalized['cell_goal'] == request['cell_goal']
    assert normalized['management_context'] == request['management_context']
    assert request['management_context']['management_summary'] not in background
    assert 'Supervisor management_context' in background
    assert 'slk_read_evidence' in background
    assert 'WORKER_SELF_REPORTED_PASS' not in background


def test_management_hash_conflict_is_not_silently_replaced(tmp_path):
    adapter = load('slk_checker_adapter.py')
    path, _, _ = _request(tmp_path)
    request = json.loads(path.read_text(encoding='utf-8'))
    request['management_context'] = {'management_action': 'SUPPLY_EVIDENCE',
        'management_summary': 'Original evidence, not a new goal.',
        'management_evidence_refs': [{'path': request['evidence_files'][0], 'sha256': '0' * 64}]}
    with pytest.raises(ValueError, match='hash changed'):
        adapter._validate_request(request)


def test_background_retains_unchanged_seam_criteria_and_last_action_order(tmp_path):
    adapter = load('slk_checker_adapter.py')
    path, _, _ = _request(tmp_path)
    request = json.loads(path.read_text(encoding='utf-8'))
    request['cell_goal'] = 'Review the full CELL including unchanged Shell and handshake seams.'
    request['d1_criteria'] = ['Changed files meet the goal.', 'The unchanged Shell handshake remains correct.']
    scope = request['review_scope']
    scope['criterion_ids'] = ['D1-001', 'D1-002']
    scope['scope_sha256'] = adapter._canonical_sha({key: scope[key] for key in
        ('include_paths', 'exclude_paths', 'criterion_ids')})
    background = adapter._background(adapter._validate_request(request))
    assert request['cell_goal'] not in background
    assert all(criterion not in background for criterion in request['d1_criteria'])
    assert background.index('slk_read_evidence(0)') < background.index('independent preliminary judgment')
    assert background.index('slk_read_evidence(1)') < background.index('independent preliminary judgment')
    assert background.index('independent preliminary judgment') < background.index('Worker D0 originals')
    assert 'entire cell_goal and every d1_criteria entry' in background
    assert 'unchanged Shell/handshake seams' in background
    assert background.index('save actual reports and evidence') < background.index('last action')
    assert 'Do not continue reviewing after handoff' in background


def _run_material_request(tmp_path, monkeypatch):
    adapter, bridge = load('slk_checker_adapter.py'), load('slk_checker_decision.py')
    request, output, repository = _request(tmp_path)
    value = json.loads(request.read_text(encoding='utf-8'))
    value['cell_goal'] = '完整目标🙂' * 1800 + 'GOAL-END'
    value['d1_criteria'] = ['全部准则🙂' * 1800 + 'CRITERIA-END']
    value['management_context'] = {'management_action': 'SUPPLY_EVIDENCE',
        'management_summary': 'Keep the complete goal and criteria. MANAGEMENT-END',
        'management_evidence_refs': value['evidence_files']}
    value['evidence_refs'] = [{'path': str(tmp_path / f'missing-{i}.log'), 'sha256': 'a' * 64}
                              for i in range(100)]
    request.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8', newline='\r\n')
    before = request.read_bytes()
    receipt = tmp_path / 'native-start.received.json'
    context = {'adapter': 'ocrv-checker', 'run_id': value['run_id'], 'cell_id': value['cell_id'],
        'message_id': 'message-materials', 'request_sha256': 'b' * 64,
        'native_request_sha256': hashlib.sha256(before).hexdigest()}
    fake, log = _fake_ocr(tmp_path)
    monkeypatch.setenv('OCRV_SLK_COMMAND_JSON', json.dumps([sys.executable, str(fake)]))
    monkeypatch.setenv('FAKE_OCR_LOG', str(log))
    monkeypatch.setenv('SLK_NATIVE_START_RECEIPT', str(receipt))
    monkeypatch.setenv('SLK_NATIVE_START_CONTEXT', json.dumps(context))
    monkeypatch.setattr(adapter, '_session_directory', lambda *_: tmp_path / 'sessions')
    monkeypatch.setattr(adapter, '_discover_capabilities', lambda *_: {'invocations': []})
    assert adapter.run(request, output, invocation_override='native-materials') == 0
    index = tmp_path / 'evidence-index.json'
    monkeypatch.setenv('SLK_CHECKER_EVIDENCE_INDEX', str(index))
    monkeypatch.setenv('SLK_CHECKER_EVIDENCE_INDEX_SHA256', adapter._sha256(index))
    return adapter, bridge, request, before, receipt, index, value


def test_native_bootstrap_reads_complete_request_catalog_and_external_d0(tmp_path, monkeypatch):
    adapter, bridge, request, before, _, index, value = _run_material_request(tmp_path, monkeypatch)
    background = (tmp_path / 'd1-background.md').read_text(encoding='utf-8')
    request_read = bridge.read_evidence(0)
    assert request_read['text'] == before.decode('utf-8')
    assert '\r\n' in request_read['text']
    assert request_read['eof'] is True and request_read['next_offset'] == len(request_read['text'])
    assert json.loads(request_read['text']) == value
    assert request.read_bytes() == before
    assert all(marker in request_read['text'] for marker in ('GOAL-END', 'CRITERIA-END', 'MANAGEMENT-END'))
    assert 'WORKER_SELF_REPORTED' not in request_read['text']
    assert not any(marker in background for marker in ('GOAL-END', 'CRITERIA-END', 'MANAGEMENT-END'))
    catalog_read = bridge.read_evidence(1)
    catalog = json.loads(catalog_read['text'])
    assert catalog_read['eof'] is True
    assert len(catalog_read['text']) > 8000
    assert catalog['evidence_refs'] == value['evidence_refs']
    assert len(catalog['evidence_gaps']) == 100
    assert all(item['reason'] == 'UNAVAILABLE' for item in catalog['evidence_gaps'])
    assert 'WORKER_SELF_REPORTED' not in catalog_read['text']
    assert catalog['evidence'][0]['index'] == 2
    original = bridge.read_evidence(catalog['evidence'][0]['index'])
    assert original['text'] == Path(value['evidence_files'][0]).read_bytes().decode('utf-8')
    assert 'WORKER_SELF_REPORTED_D0' in original['text']
    assert not Path(original['path']).is_relative_to(Path(value['repository']))
    indexed = json.loads(index.read_text(encoding='utf-8'))
    assert indexed['evidence'][0]['sha256'] == adapter._sha256(request)
    assert indexed['evidence'][1]['sha256'] == adapter._sha256(Path(catalog_read['path']))
    assert str(index) not in {item['path'] for item in indexed['evidence']}
    assert catalog_read['path'] not in {item['path'] for item in catalog['evidence']}


@pytest.mark.parametrize('damage', ['request', 'catalog', 'index', 'invocation', 'request-binding'])
def test_generated_material_index_rejects_changed_originals_and_wrong_invocation(tmp_path, monkeypatch, damage):
    _, bridge, request, _, receipt, index, _ = _run_material_request(tmp_path, monkeypatch)
    number = 0
    if damage == 'request':
        request.write_text('{}', encoding='utf-8')
    elif damage == 'catalog':
        indexed = json.loads(index.read_text(encoding='utf-8'))
        Path(indexed['evidence'][1]['path']).write_text('{}', encoding='utf-8')
        number = 1
    elif damage == 'index':
        index.write_text('{}', encoding='utf-8')
    else:
        saved = json.loads(receipt.read_text(encoding='utf-8'))
        if damage == 'invocation': saved['native_task']['id'] = 'other-invocation'
        else: saved['native_request_sha256'] = '0' * 64
        receipt.write_text(json.dumps(saved), encoding='utf-8')
    with pytest.raises(ValueError):
        bridge.read_evidence(number)


def test_read_tool_requires_request_before_review_and_d0_after_review():
    description = load('slk_checker_decision.py').READ_TOOL['description']
    assert 'request' in description and 'catalog' in description
    assert 'before independent preliminary review' in description
    assert 'Worker D0 originals only after' in description


def test_material_registration_rejects_request_not_matching_native_binding(tmp_path):
    adapter = load('slk_checker_adapter.py')
    request, _, _ = _request(tmp_path)
    normalized = adapter._validate_request(adapter._read_json(request))
    context = {'run_id': normalized['run_id'], 'cell_id': normalized['cell_id'],
        'message_id': 'message-materials', 'native_request_sha256': '0' * 64}
    with pytest.raises(adapter.RequestError, match='request hash'):
        adapter._index_materials(normalized, request, tmp_path, 'native-materials',
                                 {'invocations': []}, context)
    assert not (tmp_path / 'material-catalog.json').exists()
    assert not (tmp_path / 'evidence-index.json').exists()


def test_bootstrap_does_not_grow_with_request_material(tmp_path):
    adapter = load('slk_checker_adapter.py')
    path, _, _ = _request(tmp_path)
    original = adapter._read_json(path)
    short = adapter._background(adapter._validate_request(original))
    original['cell_goal'] *= 1000
    original['d1_criteria'][0] *= 1000
    original['management_context'] = {'management_action': 'SUPPLY_EVIDENCE',
        'management_summary': 'management summary ' * 1000,
        'management_evidence_refs': original['evidence_files']}
    original['evidence_refs'] = [{'path': str(tmp_path / f'missing-{i}.log'), 'sha256': 'a' * 64}
                                  for i in range(100)]
    assert adapter._background(adapter._validate_request(original)) == short


def test_reader_protocol_rejects_path_and_never_calls_decision(tmp_path, monkeypatch):
    bridge = load('slk_checker_decision.py')
    bind(tmp_path, monkeypatch)
    call = {'id': 1, 'method': 'tools/call', 'params': {'name': 'slk_read_evidence', 'arguments': {'index': 0, 'limit': 10}}}
    result = bridge.respond(call, lambda *_: pytest.fail('read cannot submit D1'))
    assert len(json.loads(result['result']['content'][0]['text'])['text']) == 10
    call['params']['arguments']['path'] = 'unindexed-file'
    assert bridge.respond(call)['result']['isError'] is True


def test_no_completion_is_published_for_an_action_error_or_non_decision(tmp_path, monkeypatch):
    bridge = load('slk_checker_decision.py')
    _, _, index = bind(tmp_path, monkeypatch)
    request = {'method': 'tools/call', 'params': {'name': 'slk_checker_decide'}}
    bridge._publish_completion(request, {'result': {'isError': True}})
    bridge._publish_completion({'method': 'tools/list'}, {'result': {'tools': []}})
    bridge._publish_completion({'method': 'tools/call', 'params': []}, {'error': {}})
    assert not index.with_name('review-completed.json').exists()


@pytest.mark.parametrize('related', [True, False, 'deep', 'cycle'])
def test_native_bridge_observes_only_exact_parent_under_original_launcher(tmp_path, monkeypatch, related):
    import sys
    bridge, adapter = load('slk_checker_decision.py'), load('slk_checker_adapter.py')
    _, receipt, index = bind(tmp_path, monkeypatch)
    value = json.loads(receipt.read_text())
    value['process'] = {'pid': 100, 'creation_time': 'created-100'}
    receipt.write_text(json.dumps(value), encoding='utf-8')
    monkeypatch.setitem(sys.modules, 'slk_checker_adapter', adapter)
    monkeypatch.setattr(bridge.os, 'getppid', lambda: 200)
    monkeypatch.setattr(adapter, '_process_creation_time', lambda pid: f'created-{pid}')
    parents = {200: 100 if related else 999}
    if related == 'deep':
        parents = {i: i - 1 for i in range(101, 201)}
    elif related == 'cycle':
        parents = {200: 199, 199: 200}
    monkeypatch.setattr(adapter, '_process_parents', lambda: parents)
    if not related or related == 'cycle':
        with pytest.raises(ValueError, match='launcher'):
            bridge._publish_native_process()
        assert not receipt.with_name('ocrv-native-process.json').exists()
        return
    bridge._publish_native_process()
    saved = json.loads(receipt.with_name('ocrv-native-process.json').read_text())
    assert saved['process'] == {'pid': 200, 'creation_time': 'created-200'}
    assert saved['native_start_sha256'] == adapter._sha256(receipt)
    assert saved['index_sha256'] == adapter._sha256(index)
    assert saved['native_task_id'] == 'native-A'
    assert 'verdict' not in saved and 'decision' not in saved


def test_completed_receipt_has_no_native_kill_authority():
    adapter = load('slk_checker_adapter.py')
    assert not hasattr(adapter, '_close_completed_review')


@pytest.mark.parametrize('damage', ['native', 'message', 'decision'])
def test_completion_receipt_rejects_other_invocations_and_changed_decision(tmp_path, monkeypatch, damage):
    adapter = load('slk_checker_adapter.py')
    _, receipt, _ = bind(tmp_path, monkeypatch)
    identity = json.loads(receipt.read_text(encoding='utf-8'))
    decision = tmp_path / 'role-host/checker-decision.json'
    decision.parent.mkdir()
    decision.write_text(json.dumps({'source_message_id': 'message-A', 'native_task_id': 'native-A', 'verdict': 'PASS'}), encoding='utf-8')
    complete = {**{key: identity[key] for key in ('run_id', 'cell_id', 'message_id', 'native_request_sha256')},
        'schema_version': 'slk.ocrv-completion/v1', 'native_task_id': 'native-A',
        'native_start_sha256': adapter._sha256(receipt), 'decision_path': str(decision),
        'decision_sha256': adapter._sha256(decision), 'verdict': 'PASS'}
    if damage == 'native': complete['native_task_id'] = 'other-native'
    elif damage == 'message': complete['message_id'] = 'other-message'
    else: decision.write_text('{}', encoding='utf-8')
    path = tmp_path / 'review-completed.json'
    path.write_text(json.dumps(complete), encoding='utf-8')
    with pytest.raises(ValueError):
        adapter._completed_decision(path, (receipt, identity), 'native-A')


def test_private_diagnostics_stay_archived_but_out_of_engineering_index(tmp_path):
    adapter = load('slk_checker_adapter.py')
    path, _, _ = _request(tmp_path)
    request = json.loads(path.read_text())
    private = tmp_path / 'native.stderr.txt'
    private.write_text('PRIVATE_THINKING')
    request['evidence_files'].append(str(private))
    normalized = adapter._validate_request(request)
    assert str(private) not in {row['path'] for row in normalized['evidence']}
    assert private.read_text() == 'PRIVATE_THINKING'
    background = adapter._background(normalized)
    assert 'then read the indexed originals' not in background


def test_unavailable_report_findings_are_not_empty_findings():
    adapter = load('slk_checker_adapter.py')
    assert adapter._normalized_findings(None) is None
    assert adapter._normalized_findings({}) is None
    assert adapter._normalized_findings({'comments': []}) == []


def test_legacy_missing_and_private_evidence_are_catalogued_as_gaps(tmp_path):
    adapter = load('slk_checker_adapter.py')
    path, _, _ = _request(tmp_path)
    request = adapter._read_json(path)
    missing, private = tmp_path / 'missing.log', tmp_path / 'native.stderr.txt'
    private.write_text('PRIVATE_DIAGNOSTIC')
    request['evidence_files'] += [str(missing), str(private)]
    normalized = adapter._validate_request(request)
    adapter._index_materials(normalized, path, tmp_path, 'native-materials', {})
    catalog = adapter._read_json(tmp_path / 'material-catalog.json')
    assert {(item['path'], item['reason']) for item in catalog['evidence_gaps']} == {
        (str(missing), 'UNAVAILABLE'), (str(private), 'PRIVATE_DIAGNOSTIC')}
    assert all(item['availability'] == 'AVAILABLE' for item in catalog['evidence'])
    assert 'PRIVATE_DIAGNOSTIC' not in json.dumps(normalized['evidence'])


def test_changed_path_inventory_keeps_every_path(tmp_path):
    adapter = load('slk_checker_adapter.py')
    evidence = tmp_path / 'worker-result.json'
    paths = [f'src/file-{index}.py' for index in range(1100)]
    evidence.write_text(json.dumps({'next_payload': {'changed_paths': paths}}))
    compact = adapter._compact_evidence(evidence)
    assert compact['summary']['changed_paths'] == paths
    assert compact['summary']['changed_paths_summary']['omitted'] == 0


def test_declared_nested_d0_files_enter_catalog_without_following_prose_or_private_files(tmp_path, monkeypatch):
    adapter = load('slk_checker_adapter.py')
    path, _, _ = _request(tmp_path)
    request = adapter._read_json(path)
    report = Path(request['evidence_files'][0])
    log, missing = tmp_path / 'public.log', tmp_path / 'not-created.log'
    private, credential = tmp_path / 'native.stderr.txt', tmp_path / 'credentials.json'
    log.write_text('complete public test output\n' * 3000)
    private.write_text('DO_NOT_READ')
    credential.write_text('DO_NOT_READ')
    report.write_text(json.dumps({'next_payload': {'d0': {'evidence_files': [
        str(log), str(missing), str(report), str(private), str(credential)],
        'notes': str(tmp_path / 'prose-is-not-permission.log')}}}))
    original_read = adapter._compact_evidence
    def public_only(file):
        assert file not in {private, credential}
        return original_read(file)
    monkeypatch.setattr(adapter, '_compact_evidence', public_only)
    normalized = adapter._validate_request(request)
    indexed = {item['path']: item for item in normalized['evidence']}
    assert set(indexed) == {str(report), str(log)}
    assert indexed[str(log)]['sha256'] == hashlib.sha256(log.read_bytes()).hexdigest()
    assert {(gap['path'], gap['reason']) for gap in normalized['evidence_gaps']} == {
        (str(missing), 'UNAVAILABLE'), (str(private), 'PRIVATE_DIAGNOSTIC'),
        (str(credential), 'PRIVATE_CREDENTIAL')}
    context = {'run_id': request['run_id'], 'cell_id': request['cell_id'], 'message_id': 'nested-materials',
               'native_request_sha256': adapter._sha256(path)}
    index = adapter._index_materials(normalized, path, tmp_path, 'native-nested', {}, context)
    receipt = tmp_path / 'native-start.received.json'
    receipt.write_text(json.dumps({**context, 'native_task': {'id': 'native-nested'}}))
    monkeypatch.setenv('SLK_NATIVE_START_RECEIPT', str(receipt))
    monkeypatch.setenv('SLK_CHECKER_EVIDENCE_INDEX', str(index))
    monkeypatch.setenv('SLK_CHECKER_EVIDENCE_INDEX_SHA256', adapter._sha256(index))
    bridge = load('slk_checker_decision.py')
    catalog = json.loads(bridge.read_evidence(1)['text'])
    number = next(item['index'] for item in catalog['evidence'] if item['path'] == str(log))
    original = bridge.read_evidence(number)
    assert original['eof'] is True and original['text'] == log.read_bytes().decode('utf-8')


def test_nested_locator_cannot_override_frozen_hash(tmp_path):
    adapter = load('slk_checker_adapter.py')
    path, _, _ = _request(tmp_path)
    request = adapter._read_json(path)
    log = tmp_path / 'changed.log'
    log.write_text('new bytes')
    Path(request['evidence_files'][0]).write_text(json.dumps({'d0': {'evidence_files': [str(log)]}}))
    request['evidence_refs'] = [{'path': str(log), 'sha256': '0' * 64}]
    normalized = adapter._validate_request(request)
    assert str(log) not in {item['path'] for item in normalized['evidence']}
    assert [(item['path'], item['reason']) for item in normalized['evidence_gaps']] == [(str(log), 'CHANGED')]


@pytest.mark.parametrize('locator', ['nested', 'direct', 'frozen'])
@pytest.mark.parametrize('relative', [
    'sessions/native-session-a.jsonl',
    '.opencodereview/sessions/repository/opaque-id.jsonl',
    '.codex/sessions/2026/10/17/rollout-a.jsonl',
    '.codex/archived_sessions/rollout-a.jsonl',
    'home/storages/session_projcache/sessions/session-a.json',
    'sessions/NATIVE-SESSION-A.JSONL',
    'native.stdout.txt',
    'ocrv.stdout.txt',
])
def test_native_private_materials_are_rejected_before_hash_or_read(tmp_path, monkeypatch, locator, relative):
    adapter = load('slk_checker_adapter.py')
    path, _, _ = _request(tmp_path)
    request = adapter._read_json(path)
    report = Path(request['evidence_files'][0])
    private = tmp_path / relative
    private.parent.mkdir(parents=True, exist_ok=True)
    private.write_text(json.dumps({'type': 'tool_call', 'arguments': 'PRIVATE_ARGUMENTS',
                                   'result': 'PRIVATE_RESULT'}), encoding='utf-8')
    if locator == 'nested':
        report.write_text(json.dumps({'d0': {'evidence_files': [str(private)]}}))
    elif locator == 'direct':
        request['evidence_files'].append(str(private))
    else:
        # Even an approved locator/hash is not permission to disclose native transcripts.
        request['evidence_refs'] = [{'path': str(private), 'sha256': 'a' * 64}]
    original_compact = adapter._compact_evidence

    def public_only(file):
        assert file != private.resolve(), 'private native source reached the hashing/reading boundary'
        return original_compact(file)

    monkeypatch.setattr(adapter, '_compact_evidence', public_only)
    normalized = adapter._validate_request(request)
    assert str(private) not in {item['path'] for item in normalized['evidence']}
    assert [(gap['path'], gap['reason']) for gap in normalized['evidence_gaps']] == [
        (str(private), 'PRIVATE_DIAGNOSTIC')]
    assert 'observed_sha256' not in normalized['evidence_gaps'][0]
    index = adapter._index_materials(normalized, path, tmp_path, 'private-material-test', {})
    assert str(private) not in {item['path'] for item in adapter._read_json(index)['evidence']}


@pytest.mark.parametrize('relative', ['public-d0.jsonl', 'sessions/public-test-results.log'])
def test_public_d0_logs_remain_fully_readable_after_native_session_exclusion(tmp_path, monkeypatch, relative):
    adapter = load('slk_checker_adapter.py')
    path, _, _ = _request(tmp_path)
    request = adapter._read_json(path)
    original = tmp_path / relative
    original.parent.mkdir(parents=True, exist_ok=True)
    public_text = 'Complete public D0 test output\n' * 3000 + 'EOF'
    original.write_text(public_text, encoding='utf-8')
    Path(request['evidence_files'][0]).write_text(json.dumps({'d0': {'evidence_files': [str(original)]}}))
    normalized = adapter._validate_request(request)
    assert normalized['evidence_gaps'] == []
    identity = {'run_id': request['run_id'], 'cell_id': request['cell_id'], 'message_id': 'public-d0',
                'native_request_sha256': adapter._sha256(path)}
    index = adapter._index_materials(normalized, path, tmp_path, 'public-d0', {}, identity)
    receipt = tmp_path / 'native-start.received.json'
    receipt.write_text(json.dumps({**identity, 'native_task': {'id': 'public-d0'}}))
    monkeypatch.setenv('SLK_NATIVE_START_RECEIPT', str(receipt))
    monkeypatch.setenv('SLK_CHECKER_EVIDENCE_INDEX', str(index))
    monkeypatch.setenv('SLK_CHECKER_EVIDENCE_INDEX_SHA256', adapter._sha256(index))
    reader = load('slk_checker_decision.py')
    catalog = json.loads(reader.read_evidence(1)['text'])
    number = next(item['index'] for item in catalog['evidence'] if item['path'] == str(original))
    result = reader.read_evidence(number)
    assert result['eof'] is True and result['text'] == original.read_bytes().decode('utf-8')
