"""The existing Checker bridge reads exact indexed originals, not Git substitutes."""
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

from test_ocrv_preflight import _request


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


def test_management_summary_is_present_without_changing_goal_or_inlining_log(tmp_path):
    adapter = load('slk_checker_adapter.py')
    request_path, _, _ = _request(tmp_path)
    request = json.loads(request_path.read_text(encoding='utf-8'))
    request['management_context'] = {'management_action': 'SUPPLY_EVIDENCE',
        'management_summary': 'Read the original missing log; retain the frozen candidate.',
        'management_evidence_refs': [request['evidence_files'][0]]}
    normalized = adapter._validate_request(request)
    background = adapter._background(normalized, {'invocations': []})
    assert normalized['cell_goal'] == request['cell_goal']
    assert request['management_context']['management_summary'] in background
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
    background = adapter._background(adapter._validate_request(request), {'invocations': []})
    assert request['cell_goal'] in background
    assert all(criterion in background for criterion in request['d1_criteria'])
    assert 'unchanged Shell/handshake seams' in background
    assert background.index('save actual reports and evidence') < background.index('last action')
    assert 'Do not continue reviewing after handoff' in background


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


def test_completed_receipt_cannot_close_an_unrelated_process(tmp_path, monkeypatch):
    adapter = load('slk_checker_adapter.py')
    class Process:
        pid = 100
        def poll(self): return None
    monkeypatch.setattr(adapter, '_process_creation_time', lambda _: 'created')
    monkeypatch.setattr(adapter, '_process_parents', lambda: {200: 999, 999: 0})
    with pytest.raises(ValueError, match='descendant'):
        adapter._close_completed_review(Process(), {'review_process': {'pid': 200, 'creation_time': 'created'}},
                                        {'creation_time': 'created'})


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
