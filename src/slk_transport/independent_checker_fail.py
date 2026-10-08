"""Consume a genuine independent complete FAIL through the original sealed Checker.

No review launch, synthetic managed start, PASS import or alternate authority.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from dataclasses import asdict
from pathlib import Path
from typing import Any, Mapping

from . import worker_completion as wc
from .context_review import artifact_digest, digest, git_identities, identities, read
from .contracts import canonical_json_sha256
from .platform_records import read_codex_item

SCHEMA = 'slk.ocrv-independent-fail/v1'
FIELDS = {'schema_version', 'request', 'result', 'raw_review', 'session_record', 'role_host',
          'scope_plan', 'd1_started_event_id', 'd1_incomplete_event_id',
          'owner_continuation', 'supervisor_confirmation'}


def checked_ref(value: Any) -> Path:
    if (not isinstance(value, Mapping) or set(value) != {'path', 'sha256'}
        or not isinstance(value['path'], str) or not Path(value['path']).is_absolute()
        or not wc._exact_digest(value['sha256'])):
        raise ValueError('independent FAIL reference is not closed')
    path = Path(value['path']).resolve()
    if not path.is_file() or digest(path) != value['sha256']:
        raise ValueError('independent FAIL evidence is missing or changed')
    return path


def platform_proof(value: Any, kind: str, supervisor: str) -> dict[str, Any]:
    if (not isinstance(value, Mapping)
        or set(value) != {'path', 'thread_id', 'turn_id', 'item_id', 'text_sha256'}
        or not all(isinstance(value[k], str) and value[k].strip() == value[k] and value[k]
                   for k in value) or not wc._exact_digest(value['text_sha256'])):
        raise ValueError('independent FAIL authority provenance is not closed')
    proof = read_codex_item(Path(value['path']), value['thread_id'], value['item_id'])
    if (proof['kind'] != kind or proof['source_thread_id'] != supervisor
        or proof['turn_id'] != value['turn_id'] or not proof['text']
        or hashlib.sha256(proof['text'].encode()).hexdigest() != value['text_sha256']):
        raise ValueError('actual Owner continuation or Supervisor confirmation is unproven')
    return dict(value)  # separate native provenance, not an invented Owner import decision


def management_lineage(request, projection, lineage):
    """Keep the current management TOKEN distinct from the original candidate TOKEN."""
    token = wc.resolve_authoritative_token_boundary(projection, run_id=request['run_id'],
        plan_revision=request['plan_revision'])
    if token['message_id'] == request['candidate_message_id']: return None
    from .contracts import parse_delivery
    from .native_activity import validate_native_start
    original = Path(request['native_attempt_path'])
    root = original.parent / token['message_id']
    endpoint_path, envelope_path, start_path = (root / n for n in ('endpoint.json','envelope.json','started.json'))
    delivery = parse_delivery(read(endpoint_path), read(envelope_path))
    envelope = delivery.envelope
    payload = envelope.payload
    supervisors = [r for r in projection['roles'] if r.get('role') == 'supervisor' and r.get('lifecycle') == 'active']
    original_payload = read(original / 'envelope.json')['payload']
    candidate_rows = [t for t in projection['token_history'] if t.get('message_id') == request['candidate_message_id']]
    starts = [e for e in projection['events'] if e.get('event_type') == 'TRANSPORT_STARTED'
        and wc._committed_event_details(e).get('message_id') == token['message_id']]
    if (len(supervisors) != 1 or len(candidate_rows) != 1 or len(starts) != 1
        or asdict(delivery.endpoint) != request['checker_endpoint']
        or any(getattr(envelope,k) != request[k] for k in ('run_id','go_id','cell_id','token_sequence'))
        or envelope.message_id != token['message_id'] or envelope.payload_type != 'D1_MANAGEMENT_RETURN'
        or envelope.sender_role != 'supervisor' or envelope.sender_role_instance_id != supervisors[0]['role_instance_id']
        or envelope.receiver_role_instance_id != request['checker_role_instance_id']
        or payload.get('source_d1_incomplete_event_id') not in lineage
        or payload.get('candidate_message_id') != request['candidate_message_id']
        or payload.get('candidate_payload') != original_payload
        or payload.get('candidate_payload_sha256') != request['payload_sha256']
        or candidate_rows[0].get('from_role_instance_id') != request['worker_role_instance_id']
        or candidate_rows[0].get('to_role_instance_id') != request['checker_role_instance_id']
        or any(candidate_rows[0].get(k) != request[k] for k in ('go_id','cell_id'))
        or type(candidate_rows[0].get('token_sequence')) is not int
        or candidate_rows[0]['token_sequence'] >= request['token_sequence']
        or starts[0].get('author_role_instance_id') != supervisors[0]['role_instance_id']
        or any(starts[0].get(k) != request[k] for k in ('go_id','cell_id'))):
        raise ValueError('current management return does not preserve the original candidate lineage')
    details = wc._committed_event_details(starts[0])
    refs = {k: {'path':str(p.resolve()), 'sha256':digest(p)} for k,p in
        (('endpoint',endpoint_path),('envelope',envelope_path),('start',start_path))}
    if any(details.get(k+'_sha256') != refs[n]['sha256'] for k,n in
        (('endpoint','endpoint'),('envelope','envelope'),('start_evidence','start'))):
        raise ValueError('management native evidence differs from the central committed start')
    validate_native_start(start_path,adapter=delivery.endpoint.adapter,run_id=request['run_id'],
        cell_id=request['cell_id'],message_id=envelope.message_id,request_sha256=envelope.payload_sha256)
    return dict(message_id=envelope.message_id,supervisor_role_instance_id=supervisors[0]['role_instance_id'],
        candidate_token_sequence=candidate_rows[0]['token_sequence'],current_token_sequence=request['token_sequence'],evidence=refs)


def validate(request: Mapping[str, Any]) -> dict[str, Any]:
    branch = request['independent_fail']
    if (request.get('method_version') != '4.4.2' or not isinstance(branch, Mapping)
        or set(branch) != FIELDS or branch['schema_version'] != SCHEMA
        or 'recovery_terminal' in request or 'partial_terminal' in request):
        raise ValueError('independent FAIL branch is not closed or supported')
    paths = {k: checked_ref(branch[k]) for k in ('request', 'result', 'raw_review', 'session_record', 'role_host')}
    old = read(Path(request['native_attempt_path']) / 'ocrv-request.json')
    projection = read(checked_ref({'path': request['runtime_projection_path'], 'sha256': request['runtime_projection_sha256']}))
    events = projection.get('events', [])
    by_id = {event.get('event_id'): event for event in events if isinstance(event, dict)}
    if len(by_id) != len(events): raise ValueError('central event identities are duplicated')
    lineage = []
    target = branch['d1_incomplete_event_id']
    while target is not None:
        if target in lineage or target not in by_id: raise ValueError('D1 correction lineage is missing or cyclic')
        event = by_id[target]; details = wc._committed_event_details(event)
        if (event.get('event_type') != 'D1_INCOMPLETE' or details.get('verdict') != 'INCOMPLETE'
            or event.get('author_role_instance_id') != request['checker_role_instance_id']
            or any(event.get(k) != request[k] for k in ('go_id', 'cell_id'))
            or details.get('candidate_message_id') != request['candidate_message_id']
            or type(event.get('attempt')) is not int or event['attempt'] < 1):
            raise ValueError('D1 correction lineage changed author, candidate or scope')
        lineage.append(target); target = event.get('corrects_event_id')
    start = by_id.get(branch['d1_started_event_id'], {})
    if (start.get('event_type') != 'D1_STARTED'
        or start.get('author_role_instance_id') != request['checker_role_instance_id']
        or any(start.get(k) != request[k] for k in ('go_id', 'cell_id', 'attempt'))
        or wc._committed_event_details(start).get('candidate_message_id') != request['candidate_message_id']
        or not lineage or by_id[lineage[-1]]['attempt'] != request['attempt']):
        raise ValueError('original engineering D1 start is unproven')
    source = by_id[lineage[0]]; source_details = wc._committed_event_details(source)
    correction = dict(correction_id=request['recovery_invocation_id'],
        d1_started_event_id=branch['d1_started_event_id'], d1_incomplete_event_id=lineage[0],
        native_terminal_sha256=source_details['native_terminal_sha256'],
        native_result_sha256=source_details['native_result_sha256'])
    base = {k:v for k,v in request.items() if k != 'independent_fail'}
    management = management_lineage(request, projection, lineage)
    validated = wc._validate_committed_terminal_request(base, source_only=True,
        d1_correction=correction, audit_lineage=frozenset([*lineage, branch['d1_started_event_id']]),
        audit_management_return=management)
    checker = validated['checker']
    from .role_host import RoleHost
    host = RoleHost(read(paths['role_host']), digest(paths['role_host']))
    if (host.binding['run_id'] != request['run_id'] or host.binding['plan_revision'] != request['plan_revision']
        or host.endpoint('checker') != request['checker_endpoint']
        or Path(host.credential_path('checker')).resolve() != Path(request['checker_credential_path']).resolve()
        or host.state != request['state_command'] or host.transport != request['transport_command']):
        raise ValueError('current sealed Checker RoleHost changed')
    cells = [c for c in host.binding['cells'] if c['cell_id'] == request['cell_id'] and c['go_id'] == request['go_id']]
    frozen_goal = cells[0]['payload'].get('cell_goal', cells[0]['payload'].get('task')) if len(cells) == 1 else None
    if (not isinstance(frozen_goal, str) or not frozen_goal.strip() or frozen_goal != old.get('cell_goal')
        or cells[0]['payload'].get('d1_criteria') != old.get('d1_criteria')):
        raise ValueError('frozen CELL goal or criteria changed')
    checker_role = next(r for r in projection['roles'] if r.get('role_instance_id') == checker.role_instance_id)
    row = next(r for r in checker_role['endpoints'] if r.get('endpoint_version') == checker.endpoint_version)
    supervisor_endpoint = host.endpoint('supervisor')
    supervisor_roles = [r for r in projection['roles'] if r.get('role') == 'supervisor' and r.get('lifecycle') == 'active']
    if (checker_role.get('model') != 'qwen3.8-max' or row.get('host_identity') != checker.host_id
        or row.get('session_id') != checker_role.get('session_id') or not row.get('session_id')
        or len(supervisor_roles) != 1 or supervisor_roles[0]['role_instance_id'] != supervisor_endpoint['role_instance_id']
        or supervisor_endpoint['adapter'] != 'codex-app-server'
        or supervisor_roles[0].get('session_id') != supervisor_endpoint['address'].get('thread_id')):
        raise ValueError('registered Checker runtime or Supervisor Session changed')
    supervisor = supervisor_endpoint['address']['thread_id']
    owner = platform_proof(branch['owner_continuation'], 'owner', supervisor)
    approval = platform_proof(branch['supervisor_confirmation'], 'delegation', supervisor)
    if owner['item_id'] == approval['item_id']: raise ValueError('Owner and Supervisor records are not distinct')
    native_request, result, raw = (read(paths[k]) for k in ('request', 'result', 'raw_review'))
    stable = {'schema_version', 'run_id', 'cell_id', 'repository', 'cell_goal', 'd1_criteria', 'evidence_files'}
    expected = old
    if branch['scope_plan'] is not None:
        from .context_review import validate as validate_scope
        plan = read(checked_ref(branch['scope_plan']))
        expected = validate_scope(plan, old, plan)['request']
    if (set(native_request) != stable | {'candidate', 'review_scope', 'capacity'}
        or any(native_request.get(k) != expected.get(k) for k in stable)
        or native_request['candidate'].get('kind') != 'range'
        or native_request['candidate'].get('to') != request['candidate_commit']
        or (branch['scope_plan'] is None and native_request['candidate'].get('from') != request['candidate_parent'])
        or (branch['scope_plan'] is not None and native_request['candidate'] != expected['candidate'])):
        raise ValueError('independent review changed candidate, original scope, goal or criteria')
    scope = {'include_paths': [], 'exclude_paths': [],
        'criterion_ids': [f'D1-{i:03d}' for i in range(1, len(old['d1_criteria'])+1)]}
    if native_request['review_scope'] != {**scope, 'scope_sha256': canonical_json_sha256(scope)}:
        raise ValueError('independent review is not a complete fixed-criteria scope')
    from .adapters.ocrv import OcrvAdapter
    from .contracts import Envelope
    envelope = Envelope.from_dict(read(Path(request['native_attempt_path']) / 'envelope.json'))
    OcrvAdapter().validate_existing_result(paths['result'], paths['request'], envelope, process_exit_code=2)
    manifest = raw.get('manifest', {})
    review = result.get('review', {})
    if (result.get('verdict') != 'FAIL' or result.get('reason_codes') != ['OCR_BLOCKING_FINDINGS_PRESENT']
        or review.get('status') != 'complete' or type(review.get('exit_code')) is not int or review['exit_code'] != 0
        or raw.get('status') != 'complete' or raw.get('session_id') != review.get('session_id')
        or manifest.get('schema_version') != 'ocr.run-manifest/v1' or manifest.get('operation') != 'review'
        or manifest.get('terminal_state') != 'complete' or manifest.get('run_id') != review.get('session_id')
        or any(manifest.get('execution', {}).get(k) != review.get(k) for k in ('provider', 'model'))
        or Path(str(result.get('artifacts', {}).get('raw_review', ''))).resolve() != paths['raw_review']):
        raise ValueError('only a genuine complete native FAIL is admissible')
    coverage = manifest.get('coverage', {})
    selected, completed = identities(coverage.get('selected')), identities(coverage.get('completed'))
    if (not selected or selected != completed or any(coverage.get(k) != [] for k in ('reused', 'failed', 'waived'))
        or git_identities(native_request, manifest['input'], None) != selected
        or manifest['input'].get('source_artifact_sha256') != artifact_digest(selected)):
        raise ValueError('native full-range coverage or Git fingerprints changed')
    starts, ends, done = [], [], {}
    with paths['session_record'].open(encoding='utf-8-sig') as stream:
        for line in stream:
            if not line.endswith('\n'): raise ValueError('native Session record is torn')
            row = json.loads(line)
            kind = row.get('type')
            if kind not in {'session_start', 'session_end', 'review_item_done', 'review_item_failed', 'review_item_reused'}: continue
            if row.get('sessionId') != review['session_id']: raise ValueError('native child Session changed')
            if kind == 'session_start': starts.append(row)
            elif kind == 'session_end': ends.append(row)
            elif kind == 'review_item_done':
                path = row.get('filePath')
                if path in done: raise ValueError('native review checkpoint duplicated')
                done[path] = row.get('fingerprint')
            else: raise ValueError('native review failed or reused an item')
    if (len(starts) != 1 or len(ends) != 1 or ends[0].get('run_manifest') != manifest
        or paths['session_record'].stem != review['session_id']
        or starts[0].get('parentUuid') is not None or starts[0].get('reviewMode') != 'range'
        or starts[0].get('diffFrom') != native_request['candidate']['from']
        or starts[0].get('diffTo') != request['candidate_commit']
        or starts[0].get('model') != review['model'] or starts[0].get('llmSource') != 'provider:'+review['provider']
        or Path(str(starts[0].get('cwd', ''))).resolve() != Path(request['candidate_repository']).resolve()
        or done != {p:item['fingerprint'] for p,item in selected.items()}):
        raise ValueError('actual native Session does not corroborate complete coverage')
    if datetime.fromisoformat(ends[0]['timestamp'].replace('Z', '+00:00')) <= datetime.fromisoformat(starts[0]['timestamp'].replace('Z', '+00:00')):
        raise ValueError('native review terminal time is invalid')
    evidence = dict(schema_version=SCHEMA, source_attempt=source['attempt'],
        engineering_attempt=request['attempt'], d1_incomplete_event_id=lineage[0],
        d1_started_event_id=branch['d1_started_event_id'], correction_lineage=lineage,
        candidate_message_id=request['candidate_message_id'], candidate_commit=request['candidate_commit'],
        review_invocation_id=result['review_invocation_id'], native_session_id=review['session_id'],
        registered_checker_session_id=checker_role['session_id'], selected_count=len(selected),
        occurred_at=ends[0]['timestamp'], owner_continuation=owner, supervisor_confirmation=approval,
        evidence={k: dict(branch[k]) for k in paths}, scope_plan=branch['scope_plan'],management_return=management)
    return {**validated, 'activation': {'native_attempt_path': request['native_attempt_path'],
        'candidate_message_id': request['candidate_message_id'], 'runtime_revision': request['runtime_revision'],
        'token_sequence': request['token_sequence']}, 'continuation': {**base,
        'independent_fail': evidence, 'independent_fail_request': dict(request)}}


def event_request(continuation: Mapping[str, Any]) -> dict[str, Any]:
    evidence = continuation['independent_fail']
    return dict(event_id=wc._stable_id(continuation['candidate_message_id'],
        'independent-fail-'+evidence['evidence']['result']['sha256']), run_id=continuation['run_id'],
        go_id=continuation['go_id'], cell_id=continuation['cell_id'], attempt=continuation['attempt'],
        plan_revision=continuation['plan_revision'], role_instance_id=continuation['checker_role_instance_id'],
        event_type='D1_FAILED', corrects_event_id=evidence['d1_incomplete_event_id'],
        occurred_at=evidence['occurred_at'], details={'verdict': 'FAIL',
            'candidate_message_id': continuation['candidate_message_id'], 'independent_fail': evidence,
            'native_result_path': evidence['evidence']['result']['path'],
            'native_result_sha256': evidence['evidence']['result']['sha256']})


def recorded(continuation: Mapping[str, Any], projection: Mapping[str, Any]) -> bool:
    expected = event_request(continuation)
    matches = [e for e in projection.get('events', []) if e.get('event_id') == expected['event_id']]
    if not matches: return False
    if (projection.get('run_id') != expected['run_id'] or len(matches) != 1
        or any(matches[0].get(k) != expected[k] for k in
            ('event_type', 'go_id', 'cell_id', 'attempt', 'plan_revision', 'corrects_event_id', 'occurred_at'))
        or matches[0].get('author_role_instance_id') != expected['role_instance_id']
        or wc._committed_event_details(matches[0]) != expected['details']):
        raise wc.CompletionError('CHECKER_INDEPENDENT_FAIL_REPLAY_CONFLICT', 'central FAIL replay differs')
    return True


def result(continuation: Mapping[str, Any]) -> dict[str, Any]:
    evidence = continuation['independent_fail']
    return {'status': 'CHECKER_D1_RECORDED', 'd1_verdict': 'FAIL', 'd1_event_type': 'D1_FAILED',
        'native_result_path': evidence['evidence']['result']['path'], 'native_attempt_path': continuation['native_attempt_path']}


def record(continuation: Mapping[str, Any], credential_path: Path | str) -> Mapping[str, Any]:
    # Recheck immutable evidence inside the authenticated native host, immediately before the write.
    validated = validate(continuation['independent_fail_request'])
    event = event_request(validated['continuation'])
    path = wc._write_or_reuse_stable_request(Path(continuation['result_path']).with_suffix('.d1-failed.json'), event)
    credential = wc.unprotect_dpapi_hex(credential_path)
    try:
        value = wc._run_json_command(list(continuation['state_command']), ['write', '--request', str(path)], credential=credential)
        if value.get('status') != 'recorded' or value.get('run_id') != continuation['run_id']:
            raise wc.CompletionError('CHECKER_D1_STATE_WRITE_FAILED', 'independent FAIL was not recorded')
    finally: credential = ''
    return result(continuation)
