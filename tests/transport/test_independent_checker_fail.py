from __future__ import annotations

import copy
import json
import subprocess
from pathlib import Path
from xml.sax.saxutils import escape

import pytest

from slk_transport import worker_completion as wc
from slk_transport.context_review import artifact_digest, git_identities
from slk_transport.contracts import canonical_json_sha256
from test_committed_checker_terminal import fixture, write_json, sha256
from test_contracts import endpoint_value


def independent_fixture(tmp: Path, monkeypatch: pytest.MonkeyPatch):
    repo = tmp / 'repository'
    repo.mkdir()
    def git(*args):
        return subprocess.check_output(['git', '-C', str(repo), *args], text=True).strip()
    git('init', '-q'); git('config', 'user.email', 'fixture@example.invalid')
    git('config', 'user.name', 'Fixture'); git('config', 'core.autocrlf', 'false')
    (repo / 'src').mkdir(); (repo / 'src/example.py').write_text('value = 1\n')
    git('add', '.'); git('commit', '-qm', 'base'); base = git('rev-parse', 'HEAD')
    (repo / 'src/example.py').write_text('value = 2\n')
    git('add', '.'); git('commit', '-qm', 'candidate'); head = git('rev-parse', 'HEAD')
    request, path = fixture(tmp, candidate_commit=head, candidate_parent=base)
    request['method_version'] = '4.4.2'
    native = Path(request['native_attempt_path'])
    original = json.loads((native / 'ocrv-request.json').read_text())
    review_request = {**original, 'candidate': {'kind': 'range', 'from': base, 'to': head}}
    scope = {'include_paths': [], 'exclude_paths': [], 'criterion_ids': ['D1-001']}
    review_request['review_scope'] = {**scope, 'scope_sha256': canonical_json_sha256(scope)}
    rp = write_json(tmp / 'independent/request.json', review_request)
    input_value = dict(mode='range', requested_from=base, requested_head=head,
        resolved_base=base, resolved_head=head, exact_range=base+'..'+head,
        source_artifact_sha256='0'*64)
    selected = git_identities(review_request, input_value, None)
    input_value['source_artifact_sha256'] = artifact_digest(selected)
    manifest = {'schema_version': 'ocr.run-manifest/v1', 'run_id': 'native-child',
        'operation': 'review', 'terminal_state': 'complete', 'input': input_value,
        'execution': {'provider': 'dashscope-tokenplan', 'model': 'qwen3.8-max'},
        'coverage': {'selected': list(selected.values()), 'completed': list(selected.values()),
            'reused': [], 'failed': [], 'waived': []}}
    raw_path = write_json(tmp / 'independent/raw.json',
        {'status': 'complete', 'session_id': 'native-child', 'manifest': manifest})
    result = json.loads((native / 'ocrv-result.json').read_text())
    result.update(review_invocation_id='independent-review', request_sha256=sha256(rp),
        artifacts={'raw_review': str(raw_path)}, review={**result['review'], 'session_id': 'native-child'})
    result_path = write_json(tmp / 'independent/result.json', result)
    rows = [{'type': 'session_start', 'sessionId': 'native-child', 'parentUuid': None,
        'cwd': str(repo), 'diffFrom': base, 'diffTo': head, 'reviewMode': 'range',
        'model': 'qwen3.8-max', 'llmSource': 'provider:dashscope-tokenplan',
        'timestamp': '2026-10-02T01:00:00Z'}]
    rows += [{'type': 'review_item_done', 'sessionId': 'native-child',
        'filePath': item['path'], 'fingerprint': item['fingerprint']} for item in selected.values()]
    rows += [{'type': 'session_end', 'sessionId': 'native-child', 'run_manifest': manifest,
        'timestamp': '2026-10-02T02:00:00Z'}]
    session = tmp / 'independent/native-child.jsonl'
    session.write_text(''.join(json.dumps(r)+'\n' for r in rows))
    projection_path = Path(request['runtime_projection_path'])
    projection = json.loads(projection_path.read_text())
    projection['summary']['slk_version'] = projection['runtime_snapshot']['method_version'] = '4.4.2'
    checker_id = request['checker_role_instance_id']
    def event(eid, kind, attempt, details, correction=None):
        return dict(event_id=eid, event_type=kind, author_role_instance_id=checker_id,
            go_id=request['go_id'], cell_id=request['cell_id'], attempt=attempt,
            details_json=json.dumps(details), corrects_event_id=correction)
    details = {'candidate_message_id': request['candidate_message_id']}
    projection['events'] += [event('original-start', 'D1_STARTED', 10, details),
        event('original-incomplete', 'D1_INCOMPLETE', 10, {**details, 'verdict': 'INCOMPLETE'}),
        event('corrected-incomplete', 'D1_INCOMPLETE', 9, {**details, 'verdict': 'INCOMPLETE',
            'native_terminal_sha256': 'a'*64, 'native_result_sha256': 'b'*64}, 'original-incomplete')]
    projection['administrative_snapshot']['latest_event_id'] = 'corrected-incomplete'
    roles = {}
    supervisor_thread = 'supervisor-thread'
    for role in ('supervisor', 'checker', 'worker'):
        endpoint = request['checker_endpoint'] if role == 'checker' else endpoint_value(role=role)
        endpoint['run_id'] = request['run_id']
        endpoint['role_instance_id'] = checker_id if role == 'checker' else 'RUN-A-'+role+'-001'
        if role == 'supervisor': endpoint['address']['thread_id'] = supervisor_thread
        ep = write_json(tmp / ('host/'+role+'.json'), endpoint)
        cp = Path(request['checker_credential_path']) if role == 'checker' else tmp / ('host/'+role+'.sealed')
        if role != 'checker': cp.write_text('sealed')
        roles[role] = {'endpoint_path': str(ep), 'endpoint_sha256': sha256(ep), 'credential_path': str(cp)}
    checker_role = next(r for r in projection['roles'] if r['role'] == 'checker')
    checker_role.update(model='qwen3.8-max', session_id='registered-ocrv-runtime')
    checker_role['endpoints'][0].update(host_identity=request['checker_endpoint']['host_id'],
        session_id='registered-ocrv-runtime')
    projection['roles'].append(dict(role='supervisor', role_instance_id='RUN-A-supervisor-001',
        lifecycle='active', agent_runtime='codex', session_id=supervisor_thread))
    write_json(projection_path, projection); request['runtime_projection_sha256'] = sha256(projection_path)
    host = write_json(tmp / 'host/binding.json', dict(schema_version='slk.role-host/v1',
        run_id=request['run_id'], plan_revision=request['plan_revision'],
        state_command=request['state_command'], transport_command=request['transport_command'],
        roles=roles, cells=[dict(go_id=request['go_id'], cell_id=request['cell_id'],
            payload={'cell_goal': original['cell_goal'], 'd1_criteria': original['d1_criteria']})],
        d2_criteria=['complete']))
    monkeypatch.setenv('CODEX_HOME', str(tmp / 'codex'))
    sessions = tmp / 'codex/sessions/2026/10/02'; sessions.mkdir(parents=True)
    owner = sessions / 'rollout-supervisor-thread.jsonl'
    owner_text = 'Continue this Run through D0/D1 and D2.'
    owner.write_text(json.dumps({'type': 'session_meta', 'payload': {'id': supervisor_thread,
        'originator': 'Codex Desktop'}})+'\n'+json.dumps({'type': 'event_msg', 'payload': {
        'type': 'item_completed', 'thread_id': supervisor_thread, 'turn_id': 'owner-turn',
        'item': {'id': 'owner-item', 'type': 'UserMessage', 'content': [{'type': 'text', 'text': owner_text}]}}})+'\n')
    confirmation = sessions / 'rollout-maintainer-thread.jsonl'
    approval_text = 'Approve the existing FAIL-only receiver repair design.'
    confirmation.write_text(json.dumps({'type': 'session_meta', 'payload': {'id': 'maintainer-thread',
        'originator': 'Codex Desktop'}})+'\n'+json.dumps({'type': 'response_item', 'payload': {
        'type': 'function_call_output', 'id': 'approval-item', 'name': 'send_message_to_thread',
        'namespace': 'codex_app', 'output': '<codex_delegation><source_thread_id>'+supervisor_thread+
            '</source_thread_id><input>'+escape(approval_text)+'</input></codex_delegation>',
        'internal_chat_message_metadata_passthrough': {'turn_id': 'approval-turn'}}})+'\n')
    def proof(p, thread, item, turn, text):
        return dict(path=str(p), thread_id=thread, item_id=item, turn_id=turn,
            text_sha256=canonical_text(text))
    def ref(p): return dict(path=str(p), sha256=sha256(p))
    request['immutable_sha256'] = {k:v for k,v in request['immutable_sha256'].items()
        if k in {'endpoint.json', 'envelope.json', 'started.json', 'ocrv-request.json'}}
    request['independent_fail'] = dict(schema_version='slk.ocrv-independent-fail/v1',
        request=ref(rp), result=ref(result_path), raw_review=ref(raw_path), session_record=ref(session),
        role_host=ref(host), scope_plan=None, d1_started_event_id='original-start',
        d1_incomplete_event_id='corrected-incomplete',
        owner_continuation=proof(owner, supervisor_thread, 'owner-item', 'owner-turn', owner_text),
        supervisor_confirmation=proof(confirmation, 'maintainer-thread', 'approval-item', 'approval-turn', approval_text))
    return request, path


def canonical_text(text):
    import hashlib
    return hashlib.sha256(text.encode()).hexdigest()


def test_sealed_checker_records_only_fail_correction_and_replay_writes_nothing(tmp_path, monkeypatch):
    from slk_transport.independent_checker_fail import event_request, record
    request, _ = independent_fixture(tmp_path, monkeypatch)
    validated = wc._validate_committed_terminal_request(request)
    captured = []
    monkeypatch.setattr(wc, 'unprotect_dpapi_hex', lambda _: 'sealed-checker-secret')
    def write(command, args, *, credential):
        assert credential == 'sealed-checker-secret'
        captured.append(json.loads(Path(args[-1]).read_text()))
        return {'status': 'recorded', 'run_id': request['run_id']}
    monkeypatch.setattr(wc, '_run_json_command', write)
    assert record(validated['continuation'], request['checker_credential_path'])['d1_verdict'] == 'FAIL'
    assert len(captured) == 1 and captured[0]['event_type'] == 'D1_FAILED'
    assert captured[0]['corrects_event_id'] == 'corrected-incomplete'
    assert captured[0]['attempt'] == 10
    assert captured[0]['details']['independent_fail']['source_attempt'] == 9
    current = copy.deepcopy(validated['frozen_projection'])
    event = event_request(validated['continuation'])
    current['events'].append({**{k:v for k,v in event.items() if k not in {'role_instance_id','details'}},
        'author_role_instance_id': event['role_instance_id'], 'details_json': json.dumps(event['details'])})
    current['runtime_snapshot']['runtime_revision'] += 2
    current['runtime_snapshot']['token_holder_role_instance_id'] = 'RUN-A-supervisor-001'
    monkeypatch.setenv('SLK_OCRV_RECOVERY_ROLE_INSTANCE_ID', request['checker_role_instance_id'])
    monkeypatch.setenv('SLK_OCRV_RECOVERY_INVOCATION_ID', request['recovery_invocation_id'])
    monkeypatch.setenv('SLK_OCRV_RECOVERY_ENDPOINT_VERSION', str(request['checker_endpoint_version']))
    def auth(*_): return {'status':'authenticated','role':'checker',
        'role_instance_id':request['checker_role_instance_id'],'runtime_revision':request['runtime_revision']+2}
    def forbidden(*_): pytest.fail('exact central replay must not append another event')
    result = wc.execute_committed_checker_terminal(request, request_sha256='f'*64,
        authenticate_checker=auth, load_current_projection=lambda *_:current, record_checker_d1=forbidden)
    assert result['d1_verdict'] == 'FAIL'


def test_independent_fail_is_bound_without_synthesizing_managed_start(tmp_path, monkeypatch):
    request, _ = independent_fixture(tmp_path, monkeypatch)
    result = wc._validate_committed_terminal_request(request)
    assert result['continuation']['independent_fail']['native_session_id'] == 'native-child'
    assert result['continuation']['independent_fail']['source_attempt'] == 9
    assert result['continuation']['attempt'] == 10
    assert not (tmp_path / 'independent/started.json').exists()


def test_native_tool_completion_event_is_not_mistaken_for_owner_message(tmp_path, monkeypatch):
    request, _ = independent_fixture(tmp_path, monkeypatch)
    proof = request['independent_fail']['supervisor_confirmation']
    path = Path(proof['path'])
    native = json.loads(path.read_text().splitlines()[1])['payload']
    with path.open('a', encoding='utf-8') as stream:
        stream.write(json.dumps({'type': 'event_msg', 'payload': {'type': 'item_completed',
            'thread_id': proof['thread_id'], 'turn_id': proof['turn_id'],
            'item': {**{k:native[k] for k in ('id','name','namespace','output')},
                     'type': 'FunctionCallOutput'}}})+'\n')
    assert wc._validate_committed_terminal_request(request)['checker'].role == 'checker'


@pytest.mark.parametrize('fault', ['thread_id','turn_id','output'])
def test_native_tool_double_representation_rejects_contradiction(tmp_path, monkeypatch, fault):
    request, _ = independent_fixture(tmp_path, monkeypatch)
    proof = request['independent_fail']['supervisor_confirmation']; path = Path(proof['path'])
    native = json.loads(path.read_text().splitlines()[1])['payload']
    value = {'thread_id': proof['thread_id'], 'turn_id': proof['turn_id'], 'type':'item_completed',
        'item': {**{k:native[k] for k in ('id','name','namespace','output')}, 'type':'FunctionCallOutput'}}
    if fault == 'output': value['item']['output'] = 'different'
    else: value[fault] = 'different'
    with path.open('a', encoding='utf-8') as stream:
        stream.write(json.dumps({'type':'event_msg','payload':value})+'\n')
    with pytest.raises(wc.CompletionError): wc._validate_committed_terminal_request(request)


def management_fixture(tmp, monkeypatch):
    request, path = independent_fixture(tmp, monkeypatch)
    projection_path = Path(request['runtime_projection_path']); p = json.loads(projection_path.read_text())
    native = Path(request['native_attempt_path']); endpoint = json.loads((native/'endpoint.json').read_text())
    envelope = json.loads((native/'envelope.json').read_text())
    old_payload = envelope['payload']
    envelope.update(message_id='22222222-2222-4222-8222-222222222222', token_sequence=request['token_sequence']+2,
        sender_role='supervisor', sender_role_instance_id='RUN-A-supervisor-001',
        payload_type='D1_MANAGEMENT_RETURN', payload=dict(candidate_message_id=request['candidate_message_id'],
            candidate_payload=old_payload, candidate_payload_sha256=canonical_json_sha256(old_payload),
            source_d1_incomplete_event_id='original-incomplete', management_action='ADJUST_CAPACITY',
            management_summary='Resume fixed candidate', management_evidence_refs=[request['runtime_projection_path']],
            review_policy=dict(profile='NORMAL_D1_DEFAULT',aggregate_budget='NATIVE_UNLIMITED',
                review_timeout='NATIVE_UNLIMITED',tool_rounds='TEMPLATE_DEFAULT')))
    envelope['payload_sha256'] = canonical_json_sha256(envelope['payload'])
    root = native.parent/envelope['message_id']
    ep = write_json(root/'endpoint.json',endpoint); env = write_json(root/'envelope.json',envelope)
    start = json.loads((native/'started.json').read_text())
    start.update(message_id=envelope['message_id'], request_sha256=envelope['payload_sha256'])
    sp = write_json(root/'started.json',start)
    p['events'].append(dict(event_id='management-start',event_type='TRANSPORT_STARTED',
        author_role_instance_id='RUN-A-supervisor-001',go_id=request['go_id'],cell_id=request['cell_id'],
        attempt=9,corrects_event_id=None,details_json=json.dumps(dict(message_id=envelope['message_id'],
            endpoint_sha256=sha256(ep),envelope_sha256=sha256(env),start_evidence_sha256=sha256(sp)))))
    p['token_history'].append(dict(event_type='TOKEN_HANDED_OFF',message_id=envelope['message_id'],
        go_id=request['go_id'],cell_id=request['cell_id'],token_sequence=envelope['token_sequence'],
        from_role_instance_id='RUN-A-supervisor-001',to_role_instance_id=request['checker_role_instance_id']))
    request['token_sequence'] = envelope['token_sequence']
    p['runtime_snapshot'].update(token_sequence=request['token_sequence'],latest_message_id=envelope['message_id'])
    write_json(projection_path,p); request['runtime_projection_sha256'] = sha256(projection_path)
    return request, root


@pytest.mark.parametrize('wrong_candidate',[False,True])
def test_independent_fail_preserves_original_candidate_and_current_management_token(tmp_path, monkeypatch, wrong_candidate):
    request, root = management_fixture(tmp_path,monkeypatch)
    if wrong_candidate:
        ep = root/'envelope.json'; value=json.loads(ep.read_text())
        value['payload']['candidate_message_id']='another-candidate'
        value['payload_sha256']=canonical_json_sha256(value['payload']);write_json(ep,value)
        with pytest.raises(wc.CompletionError):wc._validate_committed_terminal_request(request)
    else:
        result=wc._validate_committed_terminal_request(request)
        assert result['continuation']['token_sequence']==33


@pytest.mark.parametrize('changed_goal', [False, True])
def test_formal_six_field_host_task_is_the_frozen_goal(tmp_path, monkeypatch, changed_goal):
    request, _ = independent_fixture(tmp_path, monkeypatch)
    ref = request['independent_fail']['role_host']; path = Path(ref['path'])
    host = json.loads(path.read_text()); payload = host['cells'][0]['payload']
    host['cells'][0]['payload'] = {'cell_id': request['cell_id'], 'cell_ordinal': 1,
        'required_cell_count': 1, 'task': 'different goal' if changed_goal else payload['cell_goal'],
        'd1_criteria': payload['d1_criteria'], 'root_record_path': request['runtime_projection_path']}
    write_json(path, host); ref['sha256'] = sha256(path)
    if changed_goal:
        with pytest.raises(wc.CompletionError): wc._validate_committed_terminal_request(request)
    else:
        assert wc._validate_committed_terminal_request(request)['checker'].role == 'checker'


@pytest.mark.parametrize('fault', ['pass', 'candidate', 'scope', 'owner', 'approval', 'session', 'model', 'lineage',
                                 'legacy', 'missing-owner', 'token', 'duplicate-checkpoint'])
def test_independent_fail_rejects_scope_identity_or_authority_drift(tmp_path, monkeypatch, fault):
    request, _ = independent_fixture(tmp_path, monkeypatch)
    branch = request['independent_fail']
    if fault in {'pass', 'model'}:
        p = Path(branch['result']['path']); value = json.loads(p.read_text())
        if fault == 'pass': value['verdict'] = 'PASS'
        else: value['review']['model'] = 'another-model'
        write_json(p, value); branch['result']['sha256'] = sha256(p)
    elif fault in {'candidate', 'scope'}:
        p = Path(branch['request']['path']); value = json.loads(p.read_text())
        if fault == 'candidate': value['candidate']['to'] = 'a'*40
        else: value['review_scope']['criterion_ids'] = []
        write_json(p, value); branch['request']['sha256'] = sha256(p)
    elif fault == 'owner': branch['owner_continuation'] = copy.deepcopy(branch['supervisor_confirmation'])
    elif fault == 'approval': branch['supervisor_confirmation']['thread_id'] = 'wrong-thread'
    elif fault == 'session': branch['session_record']['sha256'] = '0'*64
    elif fault == 'legacy': request['method_version'] = '4.4.1'
    elif fault == 'missing-owner': del branch['owner_continuation']
    elif fault == 'token': request['token_sequence'] += 1
    elif fault == 'duplicate-checkpoint':
        p = Path(branch['session_record']['path']); lines=p.read_text().splitlines()
        p.write_text('\n'.join([*lines,lines[1]])+'\n');branch['session_record']['sha256']=sha256(p)
    else: branch['d1_started_event_id'] = 'another-start'
    with pytest.raises(wc.CompletionError): wc._validate_committed_terminal_request(request)
