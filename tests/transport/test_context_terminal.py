"""A terminal native blocker is consumed by the original sealed Checker, never rerun."""
import copy
import json
import os
from pathlib import Path
from dataclasses import asdict

import pytest

from slk_transport import context_review as cr
from slk_transport import worker_completion as wc
from slk_transport.adapters.ocrv import OcrvAdapter
from slk_transport.adapters.base import AdapterError
from slk_transport.native_activity import make_native_start
from test_context_review import context_fixture, write, ref
from test_ocrv_adapter import checker_endpoint
from test_role_host import prepared_host
from context_native_fixture import native_input


def terminal_fixture(tmp_path):
    envelope, _plan_path, plan, _items = context_fixture(tmp_path)
    root = tmp_path / 'failed-native'
    endpoint = checker_endpoint(tmp_path, 'context-recovery')
    write(root / 'endpoint.json', asdict(endpoint)); write(root / 'envelope.json', asdict(envelope))
    full = OcrvAdapter()._candidate_request(envelope)
    write(root / 'ocrv-preflight-request.json', full)
    all_paths = [f'file-{n:02d}.rs' for n in range(18)]
    write(root / 'ocrv-preflight.json', {'preview': {'selected_paths': all_paths}})
    write(root / 'ocrv-context-recovery-plan.json', plan)
    segment = root / 'review-segments' / 'segment-001'
    request = OcrvAdapter._make_review_segment(full, all_paths, plan['groups'][0],
        full['d1_criteria'], full['review_scope']['criterion_ids'], '1/4')
    request_path = write(segment / 'request.json', request)
    raw = copy.deepcopy(cr.read(Path(plan['sources']['raw_review']['path'])))
    raw.update(status='complete', session_id='native-child', comments=[{'severity': 'MEDIUM', 'message': 'native blocker'}])
    manifest = raw['manifest']
    manifest.update(terminal_state='complete', run_id='native-child')
    manifest['input'], items = native_input(full['repository'], full['candidate']['commit'], plan['groups'][0])
    manifest['coverage'].update(selected=items, completed=items, failed=[], reused=[])
    raw_path = write(tmp_path / 'native-child' / 'ocrv-review.json', raw)
    result = {'schema_version': 'slk.ocrv-d1-result/v1', 'run_id': envelope.run_id, 'cell_id': envelope.cell_id,
        'review_invocation_id': 'native-invocation', 'verdict': 'FAIL', 'reason_codes': ['OCR_BLOCKING_FINDINGS_PRESENT'],
        'findings': raw['comments'], 'review': {'status': 'complete', 'provider': 'dashscope-tokenplan',
        'model': 'qwen3.8-max', 'session_id': 'native-child', 'exit_code': 0}, 'evidence': [],
        'request_sha256': cr.digest(request_path), 'artifacts': {'raw_review': str(raw_path)}}
    write(segment / 'result.json', result)
    write(root / 'started.json', make_native_start(adapter=endpoint.adapter, run_id=envelope.run_id,
        cell_id=envelope.cell_id, message_id=envelope.message_id, request_sha256=envelope.payload_sha256,
        native_request_sha256=cr.digest(request_path), native_task_kind='ocrv-review',
        native_task_id='native-invocation', native_task_status='RUNNING', pid=os.getpid()))
    write(root / 'failed.json', {'schema_version': 'slk.transport-result/v1', 'message_id': envelope.message_id,
        'run_id': envelope.run_id, 'adapter': endpoint.adapter, 'status': 'failed', 'native_identity': {},
        'error_code': 'OCRV_CONTEXT_RECOVERY_INVALID', 'evidence': ['started.json']})
    session = tmp_path / 'native-child.jsonl'
    rows = [{'type': 'session_start', 'sessionId': 'native-child', 'diffCommit': full['candidate']['commit'],
             'model': 'qwen3.8-max', 'cwd': full['repository']}]
    rows += [{'type': 'review_item_done', 'sessionId': 'native-child', 'filePath': item['path'],
              'fingerprint': item['fingerprint'], 'comments': raw['comments'] if n == 0 else []}
             for n, item in enumerate(items)]
    rows.append({'type': 'session_end', 'sessionId': 'native-child', 'run_manifest': manifest})
    session.write_text(''.join(json.dumps(row) + '\n' for row in rows), encoding='utf-8')
    return root, session, envelope, endpoint


def test_native_terminal_consumer_keeps_true_subset_and_medium_blocker_without_model(tmp_path):
    root, session, envelope, _endpoint = terminal_fixture(tmp_path)
    before = {p: cr.digest(p) for p in root.rglob('*') if p.is_file()}
    basis = cr.validate_terminal(root, session, cr.digest(session))
    assert basis['result']['verdict'] == 'FAIL'
    assert len(basis['selected']) == 18 and len(basis['reused']) == 7
    assert basis['scope'] == [f'file-{n:02d}.rs' for n in range(4)]
    assert before == {p: cr.digest(p) for p in root.rglob('*') if p.is_file()}


@pytest.mark.parametrize('damage', ['request', 'artifact', 'session', 'checkpoint', 'missing-end',
                                    'duplicate-end', 'findings', 'terminal', 'pass', 'extra-segment'])
def test_terminal_consumer_fails_closed_before_any_derivation(tmp_path, damage):
    root, session, _envelope, _endpoint = terminal_fixture(tmp_path)
    segment = root / 'review-segments/segment-001'
    if damage in {'request', 'findings', 'pass'}:
        path = segment / ('request.json' if damage == 'request' else 'result.json')
        value = cr.read(path)
        if damage == 'request': value['d1_criteria'] = ['changed acceptance']
        elif damage == 'findings': value['findings'] = []
        else: value['verdict'] = 'PASS'
        write(path, value)
    elif damage == 'artifact':
        path = Path(cr.read(segment / 'result.json')['artifacts']['raw_review'])
        value = cr.read(path); value['manifest']['input']['source_artifact_sha256'] = 'f' * 64; write(path, value)
    elif damage in {'session', 'checkpoint', 'missing-end', 'duplicate-end'}:
        rows = [json.loads(line) for line in session.read_text().splitlines()]
        if damage == 'session': rows[0]['diffCommit'] = 'f' * 40
        elif damage == 'checkpoint': rows[1]['fingerprint'] = 'f' * 64
        elif damage == 'missing-end': rows.pop()
        else: rows.append(rows[-1])
        session.write_text(''.join(json.dumps(row) + '\n' for row in rows), encoding='utf-8')
    elif damage == 'extra-segment': (root / 'review-segments/segment-002').mkdir()
    else:
        value = cr.read(root / 'failed.json'); value['error_code'] = 'unrelated'; write(root / 'failed.json', value)
    with pytest.raises((ValueError, AdapterError)): cr.validate_terminal(root, session, cr.digest(session))
    assert not (root / 'role-host').exists()


def test_sealed_original_checker_authenticates_then_consumes_without_dispatch(tmp_path, monkeypatch):
    root, session, envelope, endpoint = terminal_fixture(tmp_path / 'context')
    (tmp_path / 'host').mkdir()
    host, _source, _envelope = prepared_host(tmp_path / 'host')
    host.endpoints['checker'] = asdict(endpoint)
    monkeypatch.setattr(host, '_boundary', lambda *_: {'run_id': envelope.run_id})
    monkeypatch.setattr(wc, 'unprotect_dpapi_hex', lambda *_: 'sealed-test-only')
    calls = []
    monkeypatch.setattr(host, '_authenticate', lambda role, _: calls.append(('auth', role)) or {})
    def suffix(source, original, suffix_root, _time, _projection):
        calls.append(('suffix', original.message_id))
        assert source != root and cr.read(root / 'failed.json')['status'] == 'failed'
        aggregate = cr.read(source / 'ocrv-aggregate.json')
        assert aggregate['completed_segment_count'] == 1 and aggregate['planned_segment_count'] == 4
        assert aggregate['stopped_on_blocking_finding'] is True and aggregate['verdict'] == 'FAIL'
        assert aggregate['context_recovery']['not_reviewed_paths'] == [f'file-{n:02d}.rs' for n in range(4, 11)]
        assert cr.read(source / 'ocrv-result.json')['findings'][1]['severity'] == 'MEDIUM'
        return {'status': 'CHECKER_ESCALATION_COMMITTED'}
    monkeypatch.setattr(host, '_checker_result', suffix)
    monkeypatch.setattr(OcrvAdapter, 'deliver', lambda *_: pytest.fail('consumption reran a model'))
    result = host.consume_context_terminal(root, session, cr.digest(session))
    assert result['status'] == 'CHECKER_ESCALATION_COMMITTED'
    assert calls == [('auth', 'checker'), ('suffix', envelope.message_id)]
    assert host.consume_context_terminal(root, session, cr.digest(session)) == result
    assert len(calls) == 2


def test_context_preflight_never_opens_credential_or_writes_product(tmp_path, monkeypatch):
    root, session, _envelope, endpoint = terminal_fixture(tmp_path / 'context')
    (tmp_path / 'host').mkdir()
    host, _source, _original = prepared_host(tmp_path / 'host'); host.endpoints['checker'] = asdict(endpoint)
    monkeypatch.setattr(host, '_boundary', lambda *_: {})
    monkeypatch.setattr(wc, 'unprotect_dpapi_hex', lambda *_: pytest.fail('preflight opened credential'))
    value = host.consume_context_terminal(root, session, cr.digest(session), prepare_only=True)
    assert value['status'] == 'READY_TO_CONSUME_CONTEXT_BLOCKER'
    assert not (root / 'role-host').exists()


@pytest.mark.parametrize('gate', ['boundary', 'authentication'])
def test_context_consumption_gate_failure_never_materializes_evidence(tmp_path, monkeypatch, gate):
    root, session, _envelope, endpoint = terminal_fixture(tmp_path / 'context')
    (tmp_path / 'host').mkdir()
    host, _source, _original = prepared_host(tmp_path / 'host')
    host.endpoints['checker'] = asdict(endpoint)
    def reject(*_):
        raise ValueError('exact gate rejected')
    monkeypatch.setattr(host, '_boundary', reject if gate == 'boundary' else lambda *_: {})
    monkeypatch.setattr(wc, 'unprotect_dpapi_hex', lambda *_: 'sealed-test-only')
    monkeypatch.setattr(host, '_authenticate', reject)
    with pytest.raises(ValueError, match='exact gate rejected'):
        host.consume_context_terminal(root, session, cr.digest(session))
    assert not (root / 'role-host').exists()


def test_consumed_aggregate_passes_existing_formal_checker_correction_gate(tmp_path, monkeypatch):
    root, session, envelope, endpoint = terminal_fixture(tmp_path)
    basis = cr.validate_terminal(root, session, cr.digest(session))
    native = tmp_path / 'derived'
    cr.materialize_terminal(root, native, basis)
    monkeypatch.setattr(wc, 'unprotect_dpapi_hex', lambda *_: 'sealed-test-only')
    events = []
    def state(_command, arguments, **_kwargs):
        events.append(cr.read(Path(arguments[2])))
        return {'status': 'recorded', 'run_id': envelope.run_id}
    monkeypatch.setattr(wc, '_run_json_command', state)
    continuation = {'run_id': envelope.run_id, 'go_id': envelope.go_id, 'cell_id': envelope.cell_id,
        'attempt': 1, 'plan_revision': 1, 'checker_endpoint': asdict(endpoint), 'state_command': ['test-only'],
        'native_message_id': envelope.message_id,
        'd1_correction_event_id': envelope.payload['source_d1_incomplete_event_id'],
        'd1_correction_id': wc._stable_id(envelope.message_id, 'management-review'), 'd1_correction_kind': 'management'}
    result = wc._record_checker_d1({'native_attempt_path': str(native),
        'candidate_message_id': envelope.payload['candidate_message_id']}, continuation,
        checker_credential_path=tmp_path / 'test-only', timeout_seconds=1)
    assert result['d1_verdict'] == 'FAIL'
    assert len(events) == 1 and events[0]['event_type'] == 'D1_FAILED'
    assert events[0]['corrects_event_id'] == envelope.payload['source_d1_incomplete_event_id']
    assert cr.read(root / 'failed.json')['error_code'] == 'OCRV_CONTEXT_RECOVERY_INVALID'
