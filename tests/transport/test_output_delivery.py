"""Output is evidence to deliver, never a host-reviewed engineering verdict."""
from dataclasses import asdict
import importlib.util
import json
from pathlib import Path

import pytest

from slk_transport.adapters.dsh import DshAdapter
from slk_transport.adapters.ocrv import OcrvAdapter
from slk_transport.contracts import Envelope, canonical_json_sha256
from slk_transport.role_host import RoleHost
from test_dsh_adapter import worker_endpoint, worker_envelope
from test_ocrv_adapter import candidate_envelope, checker_endpoint
from test_role_host import prepared_host
from slk_transport.evidence import AttemptStore


@pytest.mark.parametrize("body", ['plain unfinished report', '{"extra":true}', '[1,2]', ''], ids=['text','extra','array','empty'])
def test_dsh_output_has_no_body_format_gate(tmp_path, body):
    endpoint, envelope = worker_endpoint(tmp_path), worker_envelope()
    path = tmp_path / 'worker-result.json'
    path.write_text(body, encoding='utf-8')
    assert DshAdapter()._read_result(path, endpoint, envelope) == body


def test_ocrv_read_keeps_arbitrary_native_output_despite_exit_and_missing_fields(tmp_path):
    envelope = candidate_envelope(tmp_path)
    path, request = tmp_path / 'result.json', tmp_path / 'request.json'
    path.write_text('{"message":"partial result", "comments":[{"severity":"HIGH"}]}')
    request.write_text('{}')
    assert OcrvAdapter().validate_existing_result(path, request, envelope, 42) == json.loads(path.read_text())


@pytest.mark.parametrize('mode', ['raw-report', 'raw-report-exit42'])
def test_actual_dsh_adapter_preserves_original_bytes_and_exit(tmp_path, mode):
    endpoint, envelope = worker_endpoint(tmp_path, mode=mode), worker_envelope()
    attempt = AttemptStore(tmp_path / 'attempts').create(envelope)
    result = DshAdapter().deliver(endpoint, envelope, attempt)
    assert (attempt.root / 'worker-result.json').read_bytes() == b'partial report\r\nnot JSON \xff\r\n'
    assert result.native_identity['exit_code'] == (42 if mode.endswith('exit42') else 0)
    if mode.endswith('exit42'):
        assert result.status == 'failed'
        assert result.error_code == 'DSH_EXIT_NONZERO'


def test_missing_worker_candidate_is_not_replaced_by_workspace(tmp_path, monkeypatch):
    from slk_transport import worker_completion as wc
    host, source, _ = prepared_host(tmp_path)
    (source / 'worker-result.json').write_text('partial report without a candidate')
    monkeypatch.setattr(wc, 'unprotect_dpapi_hex', lambda _: 'offline-secret')
    monkeypatch.setattr(host, '_authenticate', lambda *_: None)
    sent = []
    monkeypatch.setattr(wc, '_run_json_command', lambda *args, **kwargs: sent.append(args) or {'status':'failed'})
    result = host.complete(source)
    assert 'candidate' not in json.loads(Path(result['report_path']).read_text())
    for _, arguments in sent:
        body = json.loads(Path(arguments[arguments.index('--envelope')+1]).read_text())
        assert 'candidate' not in body['payload']


@pytest.mark.parametrize('mode', ['raw-report', 'raw-report-exit42'])
def test_actual_ocrv_adapter_preserves_arbitrary_report_and_exit(tmp_path, mode):
    endpoint, envelope = checker_endpoint(tmp_path, mode), candidate_envelope(tmp_path)
    attempt = AttemptStore(tmp_path / 'attempts').create(envelope)
    result = OcrvAdapter().deliver(endpoint, envelope, attempt)
    assert (attempt.root / 'ocrv-result.json').read_bytes() == b'partial checker report\r\nnot JSON \xff\r\n'
    assert result.native_identity['exit_code'] == (42 if mode.endswith('exit42') else 0)
    assert 'verdict' not in result.native_identity
    if mode.endswith('exit42'):
        assert result.status == 'failed'


def test_missing_candidate_is_forwarded_as_interface_fact_not_native_review(tmp_path, monkeypatch):
    from slk_transport.adapters import ocrv
    endpoint, incoming = checker_endpoint(tmp_path), candidate_envelope(tmp_path)
    payload = {'report':'existing Worker report', 'candidate_status':'NOT_PROVIDED'}
    incoming = Envelope.from_dict({**asdict(incoming), 'payload_type':'WORKER_REPORT',
        'payload':payload, 'payload_sha256':canonical_json_sha256(payload)})
    attempt = AttemptStore(tmp_path / 'attempts').create(incoming)
    monkeypatch.setattr(ocrv, 'spawn', lambda *a, **k: pytest.fail('missing candidate must not run review on workspace'))
    result = OcrvAdapter().deliver(endpoint, incoming, attempt)
    assert result.status == 'failed'
    receipt = json.loads((attempt.root / 'checker-receipt.json').read_text())
    assert receipt['input_report'] == payload
    assert receipt['native_started'] is False


def test_report_body_does_not_need_d1_failure_template(tmp_path):
    raw = asdict(candidate_envelope(tmp_path))
    raw.update(sender_role='checker', receiver_role='supervisor',
               sender_role_instance_id='checker-1', receiver_role_instance_id='supervisor-1',
               payload_type='D1_FAILURE_ESCALATION', payload={'report':'Existing output; decision is owned by Checker.'})
    raw['payload_sha256'] = canonical_json_sha256(raw['payload'])
    assert Envelope.from_dict(raw).payload == raw['payload']


def test_role_host_delivers_existing_worker_output_without_semantic_continuation(tmp_path, monkeypatch):
    host, source, incoming = prepared_host(tmp_path)
    (source / 'worker-result.json').write_text('partial report, not JSON', encoding='utf-8')
    monkeypatch.setattr(host, '_boundary', lambda *_: pytest.fail('output delivery must not require TOKEN/engineering readiness'))
    seen = []
    monkeypatch.setattr(host, '_deliver_output', lambda *a, **k: seen.append((a,k)) or {'status':'OUTPUT_DELIVERED'}, raising=False)
    result = host.complete(source)
    assert result['status'] == 'OUTPUT_DELIVERED'
    assert seen


def test_native_ocrv_has_no_host_classifier():
    path = Path(__file__).resolve().parents[2] / 'integrations/ocrv/slk_checker_adapter.py'
    spec = importlib.util.spec_from_file_location('output_delivery_ocrv', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert not hasattr(module, '_classify'), 'findings/coverage/exit must not synthesize D1'


@pytest.mark.parametrize('field,value', [
    ('run_id','WRONG-RUN'), ('receiver_role_instance_id','wrong-worker'),
    ('receiver_endpoint_version',99), ('receiver_role','checker'),
])
def test_report_delivery_preserves_exact_registered_source_identity(tmp_path, monkeypatch, field, value):
    host, source, original = prepared_host(tmp_path)
    raw = asdict(original)
    raw[field] = value
    (source/'envelope.json').write_text(json.dumps(raw))
    monkeypatch.setattr(host, '_deliver_output', lambda *_: pytest.fail('wrong source may not send'))
    with pytest.raises(ValueError):
        host.complete(source)


def test_partial_review_has_no_severity_verdict_builder():
    from slk_transport import partial_review
    assert not hasattr(partial_review, '_complete_verdict'), 'partial/context recovery must not synthesize D1'


@pytest.mark.parametrize('role', ['worker', 'checker'])
def test_actual_report_path_keeps_raw_partial_files_and_deduplicates(tmp_path, monkeypatch, role):
    from slk_transport import worker_completion as wc
    from slk_transport.dispatcher import dispatch_once
    from slk_transport.native_activity import make_native_start
    from slk_transport.contracts import DeliveryResult, RESULT_SCHEMA
    host, source, incoming = prepared_host(tmp_path)
    if role == 'checker':
        incoming = Envelope.from_dict({**asdict(incoming), 'sender_role':'worker',
            'sender_role_instance_id':host.endpoint('worker')['role_instance_id'],
            'receiver_role':'checker', 'receiver_role_instance_id':host.endpoint('checker')['role_instance_id'],
            'receiver_endpoint_version':host.endpoint('checker')['endpoint_version'],
            'payload_type':'CANDIDATE_READY'})
        (source / 'envelope.json').write_text(json.dumps(asdict(incoming)))
        (source / 'endpoint.json').write_text(json.dumps(host.endpoint('checker')))
    raw = b'not JSON\r\npartial output \xff\r\n'
    (source / ('worker-result.json' if role == 'worker' else 'ocrv-result.json')).write_bytes(raw)
    partial = source / 'review-segments' / 'segment-001'
    partial.mkdir(parents=True)
    (partial / 'result.json').write_text('{"comments":[{"severity":"HIGH"}]}')
    calls = []
    class Receiver:
        def validate_address(self, endpoint):
            pass
        def deliver(self, endpoint, envelope, attempt):
            calls.append(envelope)
            attempt.write_json_once('started.json', make_native_start(adapter=endpoint.adapter,
                run_id=envelope.run_id, cell_id=envelope.cell_id, message_id=envelope.message_id,
                request_sha256=envelope.payload_sha256, native_request_sha256=envelope.payload_sha256,
                native_task_kind='test-receiver', native_task_id='test', native_task_status='RUNNING', pid=__import__('os').getpid()))
            return DeliveryResult(RESULT_SCHEMA, envelope.message_id, envelope.run_id,
                endpoint.adapter, 'completed', {}, None, ('started.json',))
    monkeypatch.setattr(wc, 'unprotect_dpapi_hex', lambda _: 'offline-secret')
    monkeypatch.setattr(host, '_authenticate', lambda *_: {'status':'authenticated'})
    def external(command, arguments, **kwargs):
        assert arguments[0] == 'send', 'output must not write D1, TOKEN or re-run recovery'
        endpoint = json.loads(Path(arguments[arguments.index('--endpoint')+1]).read_text())
        envelope = json.loads(Path(arguments[arguments.index('--envelope')+1]).read_text())
        attempts = arguments[arguments.index('--attempt-root')+1]
        return dispatch_once(endpoint, envelope, attempts, adapters={endpoint['adapter']:Receiver()}).to_dict()
    monkeypatch.setattr(wc, '_run_json_command', external)
    first, second = host.complete(source), host.complete(source)
    assert first['status'] == second['status'] == 'OUTPUT_DELIVERED'
    assert len(calls) == 1
    assert calls[0].receiver_role == ('checker' if role == 'worker' else 'supervisor')
    files = calls[0].payload['files']
    assert any(row['path'] == str((partial / 'result.json').resolve()) for row in files)
    assert (source / ('worker-result.json' if role == 'worker' else 'ocrv-result.json')).read_bytes() == raw
    assert 'verdict' not in calls[0].payload
    if role == 'worker':
        from test_worker_completion import runtime_projection
        observed = wc.inspect_worker_completion(source, runtime_projection(),
            observed_at='2099-01-01T00:00:00Z', cadence_seconds=600)
        assert observed['status'] == 'OUTPUT_DELIVERED_AWAITING_ROLE_ACTION'
        assert observed['worker_outcome'] is None


def checker_action_fixture(tmp_path, monkeypatch):
    from slk_transport import worker_completion as wc
    host, source, original = prepared_host(tmp_path)
    incoming = Envelope.from_dict({**asdict(original), 'sender_role':'worker',
        'sender_role_instance_id':host.endpoint('worker')['role_instance_id'], 'receiver_role':'checker',
        'receiver_role_instance_id':host.endpoint('checker')['role_instance_id'],
        'receiver_endpoint_version':host.endpoint('checker')['endpoint_version'], 'payload_type':'CANDIDATE_READY'})
    (source / 'envelope.json').write_text(json.dumps(asdict(incoming)))
    (source / 'endpoint.json').write_text(json.dumps(host.endpoint('checker')))
    from slk_transport.native_activity import make_native_start
    start = source / 'native-start.received.json'
    start.write_text(json.dumps(make_native_start(adapter='ocrv-checker', run_id=incoming.run_id,
        cell_id=incoming.cell_id, message_id=incoming.message_id,
        request_sha256=incoming.payload_sha256, native_request_sha256=incoming.payload_sha256,
        native_task_kind='ocrv-review', native_task_id='original-checker', native_task_status='RUNNING',
        pid=__import__('os').getpid())))
    monkeypatch.setenv('SLK_NATIVE_START_RECEIPT', str(start))
    monkeypatch.setattr(host, 'projection', lambda: {'events':[{'event_type':'TRANSPORT_STARTED',
        'cell_id':incoming.cell_id, 'attempt':1, 'details':{'message_id':incoming.message_id}}]})
    monkeypatch.setattr(host, '_boundary', lambda _: host.projection())
    monkeypatch.setattr(wc, 'unprotect_dpapi_hex', lambda _: 'offline-secret')
    return host, source, incoming


def test_checker_explicit_decision_is_an_authenticated_standard_action(tmp_path, monkeypatch):
    host, source, incoming = checker_action_fixture(tmp_path, monkeypatch)
    writes = []
    monkeypatch.setattr(host, '_authenticate', lambda role, secret: writes.append(role))
    def state(arguments, *, credential):
        request = json.loads(Path(arguments[arguments.index('--request')+1]).read_text())
        writes.append(request)
        return {'status':'recorded', 'run_id':incoming.run_id}
    monkeypatch.setattr(host, '_state_json', state)
    result = host.record_checker_decision(source, 'FAIL')
    assert result['verdict'] == 'FAIL'
    assert writes[0] == 'checker'
    assert writes[-1]['event_type'] == 'D1_FAILED'
    assert writes[-1]['details']['decision_source'] == 'CHECKER_EXPLICIT'


@pytest.mark.parametrize("damage", ["caller", "run", "checker", "candidate", "command", "authority"])
def test_explicit_checker_action_rejects_identity_or_authority_drift_before_state_write(tmp_path, monkeypatch, damage):
    from slk_transport import worker_completion as wc
    host, source, incoming = checker_action_fixture(tmp_path, monkeypatch)
    if damage == "caller":
        monkeypatch.delenv("SLK_NATIVE_START_RECEIPT")
    elif damage in {"run", "checker", "candidate"}:
        value = asdict(incoming)
        if damage == "run": value["run_id"] = "OTHER-RUN"
        if damage == "checker": value["receiver_role_instance_id"] = "other-checker"
        if damage == "candidate":
            value["payload"] = {**value["payload"], "candidate":{"kind":"commit","commit":"b"*40}}
            value["payload_sha256"] = canonical_json_sha256(value["payload"])
        (source/"envelope.json").write_text(json.dumps(value))
    elif damage == "command":
        value = host.endpoint("checker")
        value["address"] = {**value["address"], "command":["other-command"]}
        (source/"endpoint.json").write_text(json.dumps(value))
    def auth(*_):
        if damage == "authority": raise ValueError("ROLE_HOST_AUTHORITY_INVALID")
        return {"status":"authenticated"}
    monkeypatch.setattr(host, "_authenticate", auth)
    monkeypatch.setattr(host, "_state_json", lambda *_a, **_k: pytest.fail("unproved action wrote state"))
    with pytest.raises(ValueError):
        host.record_checker_decision(source, "PASS")
    assert not (source/"role-host"/"checker-decision.json").exists()


def test_legacy_terminal_recorder_cannot_invent_incomplete(tmp_path, monkeypatch):
    from slk_transport import worker_completion as wc
    monkeypatch.setattr(wc, 'unprotect_dpapi_hex', lambda *_: pytest.fail('legacy suffix must not write D1'))
    with pytest.raises(wc.CompletionError, match='explicit'):
        wc._record_checker_d1({}, {}, checker_credential_path=tmp_path / 'unused', timeout_seconds=1)


def test_supervisor_raw_output_is_saved_without_guessing_a_command(tmp_path, monkeypatch):
    host, source, original = prepared_host(tmp_path)
    incoming = Envelope.from_dict({**asdict(original), 'sender_role':'checker',
        'sender_role_instance_id':host.endpoint('checker')['role_instance_id'],
        'receiver_role':'supervisor', 'receiver_role_instance_id':host.endpoint('supervisor')['role_instance_id'],
        'receiver_endpoint_version':host.endpoint('supervisor')['endpoint_version'],
        'payload_type':'D1_REPORT'})
    (source / 'envelope.json').write_text(json.dumps(asdict(incoming)))
    (source / 'endpoint.json').write_text(json.dumps(host.endpoint('supervisor')))
    raw = b'Investigate further. Not a closed action template.\r\n\xff'
    (source / 'supervisor-result.json').write_bytes(raw)
    monkeypatch.setattr(host, '_boundary', lambda *_: pytest.fail('report must not need TOKEN'))
    result = host.complete(source)
    assert result['status'] == 'OUTPUT_SAVED'
    assert (source / 'supervisor-result.json').read_bytes() == raw
    assert not (source / 'role-host' / 'supervisor-decision.json').exists()


def test_real_job_relays_missing_candidate_receipt_to_supervisor_once(tmp_path, monkeypatch):
    import argparse
    import os
    from slk_transport import cli, worker_completion as wc
    from slk_transport.contracts import DeliveryResult, RESULT_SCHEMA
    from slk_transport.dispatcher import dispatch_once
    from slk_transport.native_activity import make_native_start
    host, source, original = prepared_host(tmp_path)
    payload = {'report':'raw Worker output without candidate', 'candidate_status':'NOT_PROVIDED'}
    incoming = Envelope.from_dict({**asdict(original), 'sender_role':'worker',
        'sender_role_instance_id':host.endpoint('worker')['role_instance_id'],
        'receiver_role':'checker', 'receiver_role_instance_id':host.endpoint('checker')['role_instance_id'],
        'receiver_endpoint_version':host.endpoint('checker')['endpoint_version'],
        'payload_type':'WORKER_REPORT', 'payload':payload, 'payload_sha256':canonical_json_sha256(payload)})
    endpoint_path = source / 'endpoint.json'
    envelope_path = source / 'envelope.json'
    endpoint_path.write_text(json.dumps(host.endpoint('checker')))
    envelope_path.write_text(json.dumps(asdict(incoming)))
    monkeypatch.setattr(cli, 'load_role_host', lambda _: host)
    monkeypatch.setattr(cli, 'ADAPTERS', {'ocrv-checker':OcrvAdapter()})
    monkeypatch.setattr(wc, 'unprotect_dpapi_hex', lambda _: 'offline-secret')
    monkeypatch.setattr(host, '_authenticate', lambda *_: None)
    # Read-only lifecycle state is required; a report still needs no TOKEN,
    # engineering result, D1 decision or engineering-state mutation.
    monkeypatch.setattr(host, 'projection', lambda: {'summary': {'state': 'active'}})
    calls = []
    class Supervisor:
        def validate_address(self, endpoint):
            pass
        def deliver(self, endpoint, envelope, attempt):
            calls.append(envelope)
            attempt.write_json_once('started.json', make_native_start(adapter=endpoint.adapter,
                run_id=envelope.run_id, cell_id=envelope.cell_id, message_id=envelope.message_id,
                request_sha256=envelope.payload_sha256, native_request_sha256=envelope.payload_sha256,
                native_task_kind='test-supervisor', native_task_id='test', native_task_status='RUNNING', pid=os.getpid()))
            return DeliveryResult(RESULT_SCHEMA, envelope.message_id, envelope.run_id,
                endpoint.adapter, 'completed', {}, None, ('started.json',))
    def transport(command, arguments, **kwargs):
        assert arguments[0] == 'send'
        endpoint = json.loads(Path(arguments[arguments.index('--endpoint')+1]).read_text())
        envelope = json.loads(Path(arguments[arguments.index('--envelope')+1]).read_text())
        return dispatch_once(endpoint, envelope, arguments[arguments.index('--attempt-root')+1],
            adapters={endpoint['adapter']:Supervisor()}).to_dict()
    monkeypatch.setattr(wc, '_run_json_command', transport)
    args = argparse.Namespace(endpoint=endpoint_path, envelope=envelope_path, attempt_root=tmp_path/'job-attempts')
    assert cli._job(args) == cli._job(args) == 3
    assert len(calls) == 1
    assert calls[0].receiver_role == 'supervisor'
    assert calls[0].payload['input_report'] == payload
    assert calls[0].payload['native_started'] is False
    receipt_path = next(Path(row['path']) for row in calls[0].payload['files'] if row['path'].endswith('checker-receipt.json'))
    assert json.loads(receipt_path.read_text())['error_code'] == 'OCRV_CANDIDATE_NOT_PROVIDED'


@pytest.mark.parametrize('failure', ['send-failed', 'send-raised', 'host-raised'])
def test_job_returns_delivery_failure_separately_from_saved_native_success(
    tmp_path, monkeypatch, capsys, failure,
):
    import argparse
    from slk_transport import cli, worker_completion as wc
    host, source, _ = prepared_host(tmp_path)
    native_bytes = (source / 'completed.json').read_bytes()
    native_result = json.loads(native_bytes)
    monkeypatch.setattr(cli, 'load_role_host', lambda _: host)
    monkeypatch.setattr(wc, 'unprotect_dpapi_hex', lambda _: 'offline-secret')
    sends = []

    def send(command, arguments, **kwargs):
        assert arguments[0] == 'send'
        sends.append(arguments)
        if failure == 'send-raised':
            raise OSError('receiver pipe disconnected')
        return {'status':'failed', 'error_code':'RECEIVER_UNREACHABLE',
                'message':'receiver pipe disconnected'}

    def authenticate(*args):
        if failure == 'host-raised':
            raise OSError('role credential service unavailable')

    monkeypatch.setattr(host, '_authenticate', authenticate)
    monkeypatch.setattr(wc, '_run_json_command', send)
    args = argparse.Namespace(endpoint=source/'endpoint.json', envelope=source/'envelope.json',
                              attempt_root=source.parents[1])
    exit_code = cli._job(args)
    output = json.loads(capsys.readouterr().out)

    assert exit_code != 0, 'native completion must not hide an unconfirmed report delivery'
    assert output['status'] == 'failed'
    assert output['native_result'] == native_result
    delivery = output['output_delivery']
    assert delivery['status'] in {'OUTPUT_DELIVERY_UNCONFIRMED', 'HOST_HANDOFF_FAILED'}
    error = delivery.get('delivery', delivery)
    assert error['message'] == ('role credential service unavailable' if failure == 'host-raised'
                                else 'receiver pipe disconnected')
    assert len(sends) == (0 if failure == 'host-raised' else 1), 'no automatic retry'
    assert (source / 'completed.json').read_bytes() == native_bytes


@pytest.mark.parametrize('body', ['plain partial report', '{"extra":true}', '', None])
def test_ow_inspects_native_terminal_without_reviewing_worker_body(tmp_path, body):
    from slk_transport import worker_completion as wc
    from test_worker_completion import runtime_projection
    host, source, _ = prepared_host(tmp_path)
    path = source / 'worker-result.json'
    if body is None:
        path.unlink()
    else:
        path.write_text(body, encoding='utf-8')
    result = wc.inspect_worker_completion(source, runtime_projection(),
        observed_at='2099-01-01T00:00:00Z', cadence_seconds=600)
    assert result['worker_outcome'] is None, 'native completion is not a Worker engineering decision'
    assert result['status'] == 'WORKER_COMPLETION_HANDOFF_MISSING'
    assert result['candidate'] is None


def test_ow_keeps_native_failure_without_requiring_any_worker_result(tmp_path):
    from slk_transport import worker_completion as wc
    from test_worker_completion import runtime_projection
    _, source, _ = prepared_host(tmp_path)
    terminal = json.loads((source / 'completed.json').read_text())
    terminal.update(status='failed', error_code='DSH_EXIT_NONZERO', native_identity={'exit_code':42})
    (source / 'completed.json').unlink()
    (source / 'failed.json').write_text(json.dumps(terminal))
    (source / 'worker-result.json').write_bytes(b'partial \xff')
    result = wc.inspect_worker_completion(source, runtime_projection(),
        observed_at='2099-01-01T00:00:00Z', cadence_seconds=600)
    assert result['status'] == 'WORKER_EXECUTION_FAILURE'
    assert result['worker_outcome'] is None
    assert result['blocker']['cause'] == 'DSH_EXIT_NONZERO'


def test_existing_inspection_exposes_later_job_delivery_error_without_resending(tmp_path, monkeypatch):
    from slk_transport.recovery import inspect_delivery
    _, source, incoming = prepared_host(tmp_path)
    jobs = source.parents[1] / '.jobs'
    jobs.mkdir()
    native = json.loads((source / 'completed.json').read_text())
    output_delivery = {'status':'OUTPUT_DELIVERY_UNCONFIRMED',
        'delivery':{'status':'failed', 'error_code':'RECEIVER_UNREACHABLE', 'message':'pipe closed'}}
    (jobs / f'{incoming.message_id}.stdout.txt').write_text(json.dumps({
        'status':'failed', 'run_id':incoming.run_id, 'message_id':incoming.message_id,
        'native_result':native, 'output_delivery':output_delivery}))
    monkeypatch.setattr('slk_transport.recovery.dispatch_once',
                        lambda *a, **k: pytest.fail('inspection cannot send or retry'))
    inspected = inspect_delivery(source.parents[1], json.loads((source/'endpoint.json').read_text()), asdict(incoming))
    assert inspected['status'] == 'ALREADY_STARTED'
    assert inspected['ack_scope'] == 'NATIVE_RECEIVE_START_ONLY'
    assert inspected['output_delivery'] == output_delivery
    assert inspected['native_result'] == native


def test_existing_inspection_does_not_guess_unobserved_subsequent_delivery(tmp_path):
    from slk_transport.recovery import inspect_delivery
    _, source, incoming = prepared_host(tmp_path)
    inspected = inspect_delivery(source.parents[1], json.loads((source/'endpoint.json').read_text()), asdict(incoming))
    assert inspected['status'] == 'ALREADY_STARTED'
    assert inspected['output_delivery']['status'] == 'UNOBSERVED'


@pytest.mark.parametrize('drift', [False, True])
def test_saved_exact_retry_is_read_without_new_send_or_identity_drift(tmp_path, drift):
    import os
    from slk_transport.desktop_current_turn import resolve_delivery_start
    from slk_transport.native_activity import make_native_start
    target, incoming = checker_endpoint(tmp_path), candidate_envelope(tmp_path)
    original = tmp_path/'attempts'/incoming.run_id/incoming.message_id
    retry = original/'recovery'/'exact-1'/incoming.run_id/incoming.message_id
    retry.mkdir(parents=True)
    (retry/'endpoint.json').write_text(json.dumps(asdict(target)))
    envelope = asdict(incoming)
    if drift:
        envelope['cell_id'] = 'WRONG-CELL'
    (retry/'envelope.json').write_text(json.dumps(envelope))
    start = make_native_start(adapter=target.adapter, run_id=incoming.run_id,
        cell_id=incoming.cell_id, message_id=incoming.message_id,
        request_sha256=incoming.payload_sha256, native_request_sha256=incoming.payload_sha256,
        native_task_kind='ocrv-review', native_task_id='original-checker', native_task_status='RUNNING', pid=os.getpid())
    (retry/'started.json').write_text(json.dumps(start))
    if drift:
        with pytest.raises(ValueError):
            resolve_delivery_start(original, asdict(target), asdict(incoming))
    else:
        path, observed = resolve_delivery_start(original, asdict(target), asdict(incoming))
        assert path == retry/'started.json'
        assert observed['message_id'] == incoming.message_id


@pytest.mark.parametrize('started', [True, False])
@pytest.mark.parametrize('receipt', [True, False])
def test_migration_never_resends_a_saved_legacy_handoff_under_a_new_id(tmp_path, monkeypatch, started, receipt):
    import os
    from slk_transport import worker_completion as wc
    from slk_transport.native_activity import make_native_start
    host, source, incoming = prepared_host(tmp_path)
    root = source / 'role-host'
    root.mkdir(exist_ok=True)
    target = host.endpoint('checker')
    old = Envelope.from_dict({**asdict(incoming), 'message_id':wc._stable_id(incoming.message_id, 'candidate-ready'),
        'sender_role':'worker', 'sender_role_instance_id':host.endpoint('worker')['role_instance_id'],
        'receiver_role':'checker', 'receiver_role_instance_id':target['role_instance_id'],
        'receiver_endpoint_version':target['endpoint_version'], 'payload_type':'CANDIDATE_READY'})
    legacy = source / 'worker-continuation'
    native = legacy / 'checker-attempts' / old.run_id / old.message_id
    native.mkdir(parents=True)
    (native/'endpoint.json').write_text(json.dumps(target))
    (native/'envelope.json').write_text(json.dumps(asdict(old)))
    if started:
        (native/'started.json').write_text(json.dumps(make_native_start(adapter=target['adapter'],
            run_id=old.run_id, cell_id=old.cell_id, message_id=old.message_id,
            request_sha256=old.payload_sha256, native_request_sha256=old.payload_sha256,
            native_task_kind='test-receiver', native_task_id='original-delivery',
            native_task_status='RUNNING', pid=os.getpid())))
    saved = {'status':'CHECKER_STARTED', 'source_message_id':incoming.message_id,
        'source_sha256':host._source_sha256(source, 'worker'), 'binding_sha256':host.digest,
        'native_attempt_path':str(native)}
    if receipt:
        (root/'result.json').write_text(json.dumps(saved))
    else:
        (root/'continuation.json').write_text(json.dumps({'source_message_id':incoming.message_id}))
        (legacy/'checker-endpoint.json').write_text(json.dumps(target))
        (legacy/'candidate-envelope.json').write_text(json.dumps(asdict(old)))
    original_receipt = (root/('result.json' if receipt else 'continuation.json')).read_bytes()
    monkeypatch.setattr(wc, '_run_json_command', lambda *a, **k: pytest.fail('no new ID, retry or state write'))
    monkeypatch.setattr(wc, 'unprotect_dpapi_hex', lambda _: 'offline-secret')
    monkeypatch.setattr(host, '_authenticate', lambda *_: None)
    result = host.complete(source)
    assert result['status'] == ('OUTPUT_DELIVERED' if started else 'OUTPUT_DELIVERY_UNCONFIRMED')
    assert (root/('result.json' if receipt else 'continuation.json')).read_bytes() == original_receipt
    assert not (root/'output-envelope.json').exists()


@pytest.mark.parametrize('damage', ['failure', 'candidate', 'round', 'missing-action'])
def test_explicit_supervisor_action_keeps_identity_and_intent_guards(tmp_path, monkeypatch, damage):
    from slk_transport import worker_completion as wc
    from test_role_host import supervisor_result_fixture
    host, source, incoming, request, projection = supervisor_result_fixture(tmp_path)
    if damage == 'missing-action':
        incoming = Envelope.from_dict({**asdict(incoming), 'payload_type':'D1_INCOMPLETE_ESCALATION'})
        request.update(operation='management', decision={})
    else:
        key = {'failure':'d1_failure_event_id', 'candidate':'failed_candidate_sha256', 'round':'rework_round'}[damage]
        request['decision'][key] = 77 if damage == 'round' else 'unrelated'
    (source/'supervisor-result.json').write_text(json.dumps(request))
    monkeypatch.setattr(wc, 'unprotect_dpapi_hex', lambda _: pytest.fail('invalid explicit action used authority'))
    with pytest.raises(wc.CompletionError) as error:
        host._supervisor_result(source, incoming, source/'role-host', '2026-10-09T00:00:00Z')
    assert error.value.error_code == 'SUPERVISOR_ACTION_INVALID'


@pytest.mark.parametrize('d2', [False, True])
def test_supervisor_explicit_action_is_not_reviewed_for_report_format_or_evidence(tmp_path, monkeypatch, d2):
    from slk_transport import worker_completion as wc
    from test_role_host import supervisor_result_fixture
    host, source, incoming, request, projection = supervisor_result_fixture(tmp_path, d2=d2)
    request['additional_context'] = 'preserve, do not review'
    request['decision']['evidence_refs'] = ['unavailable evidence remains reported, not a delivery gate']
    request['decision']['additional_context'] = 'not a closed field set'
    if not d2:
        payload = {**incoming.payload, 'rework_round':2}
        incoming = Envelope.from_dict({**asdict(incoming), 'payload':payload,
                                      'payload_sha256':canonical_json_sha256(payload)})
        request['decision'].update(rework_round=2, findings=['Supervisor guidance is not verbatim OCRV findings'],
                                   investigation_mode='BOUNDED_OWNER_APPROVED_INVESTIGATION')
    (source/'supervisor-result.json').write_text(json.dumps(request))
    monkeypatch.setattr(host, '_boundary', lambda _: projection)
    monkeypatch.setattr(host, 'projection', lambda: projection)
    monkeypatch.setattr(wc, 'unprotect_dpapi_hex', lambda _: 'offline-secret')
    monkeypatch.setattr(host, '_authenticate', lambda *_: None)
    writes, sends = [], []
    def state(arguments, **kwargs):
        writes.append(json.loads(Path(arguments[-1]).read_text()))
        return {'status':'recorded', 'run_id':incoming.run_id}
    monkeypatch.setattr(host, '_state_json', state)
    monkeypatch.setattr(host, '_committed_delivery', lambda *_: False)
    monkeypatch.setattr(host, '_send_owned', lambda root, envelope, *a, **k:
        sends.append(envelope) or {'status':'OWNED_HANDOFF_COMMITTED'})
    (source/'role-host').mkdir()
    result = host._supervisor_result(source, incoming, source/'role-host', '2026-10-09T00:00:00Z')
    assert result['status'] == ('SUPERVISOR_D2_RECORDED' if d2 else 'OWNED_HANDOFF_COMMITTED')
    assert writes[-1]['event_type'] == ('D2_PASSED' if d2 else 'REWORK_REQUESTED')
    if not d2:
        assert sends[0].payload == request['decision']


@pytest.mark.parametrize('kind,key', [('D1_FAILURE_ESCALATION','d1_failure_event_id'),
    ('D1_INCOMPLETE_ESCALATION','d1_incomplete_event_id'), ('D2_READY','d1_event_id'),
    ('D1_MANAGEMENT_RETURN','source_d1_incomplete_event_id'),
    ('D1_REPORT','source_message_id'), ('CANDIDATE_READY','source_message_id')])
def test_outgoing_handoff_keeps_second_native_attempt(tmp_path, kind, key):
    host, source, original = prepared_host(tmp_path)
    value = asdict(original)
    sender, receiver = (('worker','checker') if kind == 'CANDIDATE_READY' else
                        ('supervisor','checker') if kind == 'D1_MANAGEMENT_RETURN' else ('checker','supervisor'))
    value.update(sender_role=sender, receiver_role=receiver,
        sender_role_instance_id=host.endpoint(sender)['role_instance_id'],
        receiver_role_instance_id=host.endpoint(receiver)['role_instance_id'],
        receiver_endpoint_version=host.endpoint(receiver)['endpoint_version'])
    value.update(payload_type=kind, payload={key:'original-second-attempt'},
        payload_sha256=canonical_json_sha256({key:'original-second-attempt'}))
    outgoing = Envelope.from_dict(value)
    event = {'event_id':'original-second-attempt', 'event_type':'D1_INCOMPLETE' if kind == 'D1_MANAGEMENT_RETURN' else
             'D1_FAILED' if key.startswith('d1_') else 'TRANSPORT_STARTED',
        'go_id':outgoing.go_id, 'cell_id':outgoing.cell_id, 'attempt':2,
        'details':{'message_id':'original-second-attempt'}}
    assert host._outgoing_attempt(outgoing, {'events':[event]}) == 2
