"""Explicit CLI recovery through real wrapper/native files, without a provider."""
import importlib.util
import json
from pathlib import Path
import sys
import uuid
from dataclasses import asdict

import pytest

from slk_transport import role_host as hosts, worker_completion as wc
from test_ocrv_adapter import prepared_ocrv_resume_source
from test_role_host import prepared_host

ROOT = Path(__file__).resolve().parents[2]


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'integrations/ocrv' / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def prepared(tmp_path, monkeypatch, damage='partial'):
    adapter = load('slk_checker_adapter')
    monkeypatch.setitem(sys.modules, 'slk_checker_adapter', adapter)
    original_host, source, endpoint, envelope, request = prepared_ocrv_resume_source(tmp_path, monkeypatch, adapter, damage)
    (tmp_path / 'host').mkdir()
    host, _, _ = prepared_host(tmp_path / 'host')
    host.endpoints['checker'] = asdict(endpoint)
    checker_path = Path(host.binding['roles']['checker']['endpoint_path'])
    checker_path.write_text(json.dumps(asdict(endpoint)))
    host.binding['roles']['checker']['endpoint_sha256'] = wc._sha256(checker_path)
    binding = tmp_path / 'binding.json'
    binding.write_text(json.dumps(host.binding))
    host.digest = wc._sha256(binding)
    monkeypatch.setattr(hosts, 'load_role_host', lambda _: host)
    projection = {'summary': {'run_id': envelope.run_id, 'state': 'active'},
                  'runtime_snapshot': {'runtime_revision': 9}, 'events': original_host.projection()['events'],
                  'native_invocations': []}
    monkeypatch.setattr(host, 'projection', lambda: projection)
    monkeypatch.setattr(host, '_boundary', lambda *_a, **_k: projection)
    monkeypatch.setattr(host, 'inspect_recovery_authority', lambda *_: {'status': 'SUPERVISOR_RECOVERY_AUTHENTICATED'})
    monkeypatch.setattr(host, '_authenticate', lambda *_: {'runtime_revision': 9})
    monkeypatch.setattr(wc, 'unprotect_dpapi_hex', lambda *_: 'isolated-test-secret')
    monkeypatch.setenv('CODEX_THREAD_ID', host.endpoint('supervisor')['address']['thread_id'])
    monkeypatch.setenv('OCRV_RUNTIME_ROOT', str(tmp_path / 'native-runtime'))
    monkeypatch.setattr(adapter, '_session_directory', lambda *_: source)
    identity = str(uuid.uuid4())
    args = ['slk_checker_recovery.py', '--slk-resume-review', '--binding', str(binding),
        '--sha256', host.digest, '--source-attempt', str(source), '--resume-session', 'original-session',
        '--invocation-id', identity]
    monkeypatch.setattr(sys, 'argv', args)
    return adapter, load('slk_checker_recovery'), host, source, envelope, identity


FAKE_NATIVE = r'''
import hashlib, json, os, pathlib, sys, time
args = sys.argv[1:]
receipt = pathlib.Path(os.environ['SLK_NATIVE_START_RECEIPT'])
source = receipt.parent
deadline = time.monotonic() + 5
while not (source / 'ocrv-native-source.json').exists() and time.monotonic() < deadline:
    time.sleep(.01)
start = json.loads(receipt.read_text())
native = json.loads((source / 'ocrv-native-source.json').read_text())
request = json.loads(pathlib.Path(native['request_path']).read_text())
index = pathlib.Path(os.environ['SLK_CHECKER_EVIDENCE_INDEX'])
process = {'schema_version':'slk.ocrv-native-process/v1',
    **{key:start[key] for key in ('run_id','cell_id','message_id','native_request_sha256')},
    'native_task_id':start['native_task']['id'], 'native_start_sha256':hashlib.sha256(receipt.read_bytes()).hexdigest(),
    'index_path':str(index), 'index_sha256':hashlib.sha256(index.read_bytes()).hexdigest(),
    'launcher_process':start['process'], 'process':start['process']}
(source / 'ocrv-native-process.json').write_text(json.dumps(process))
session_id = 'resumed-' + start['native_task']['id']
directory = pathlib.Path(native['session_directory'])
directory.mkdir(parents=True, exist_ok=True)
rows = [
 {'type':'session_start','sessionId':session_id,'uuid':'header','timestamp':'2026-10-01T00:00:00Z',
  'cwd':request['repository'], 'resumedFrom':args[args.index('--resume')+1]},
 {'type':'llm_request','sessionId':session_id,'uuid':'request','timestamp':'2026-10-01T00:00:01Z',
  'messages':[{'content':native['marker']}]},
 {'type':'session_end','sessionId':session_id,'timestamp':'2026-10-01T00:00:02Z',
  'duration_seconds':2, 'run_manifest':{'files':[{'path':'completed.go','status':'complete'}]}}]
(directory / (session_id + '.jsonl')).write_text(''.join(json.dumps(row)+'\n' for row in rows))
pathlib.Path(args[args.index('--output')+1]).write_text(json.dumps({'status':'partial','comments':[]}))
(source / 'native-argv.json').write_text(json.dumps(args))
'''


def test_cli_partial_resume_preserves_originals_reports_unique_identity_and_enters_census(tmp_path, monkeypatch, capsys):
    adapter, recovery, host, source, envelope, identity = prepared(tmp_path, monkeypatch)
    old = {path.relative_to(source): path.read_bytes() for path in source.rglob('*') if path.is_file()}
    script = tmp_path / 'fake_native.py'
    script.write_text(FAKE_NATIVE)
    monkeypatch.setenv('OCRV_SLK_COMMAND_JSON', json.dumps([sys.executable, str(script)]))
    monkeypatch.setattr(adapter, '_discover_capabilities', lambda *_: {'invocations': []})
    reports = []
    def send(_cmd, args, **_kwargs):
        reports.append(wc._read_object(Path(args[args.index('--envelope') + 1]), 'report'))
        return {'status': 'started'}
    monkeypatch.setattr(wc, '_run_json_command', send)
    assert recovery.main() == 3  # Native rc0 without explicit D1 remains incomplete.
    result = json.loads(capsys.readouterr().out)
    fresh = source / 'review-corrections' / identity
    assert Path(result['source_attempt']) == fresh
    assert all((source / name).read_bytes() == data for name, data in old.items())
    argv = json.loads((fresh / 'native-argv.json').read_text())
    assert argv[argv.index('--resume') + 1] == 'original-session'
    assert (fresh / 'started.json').is_file() and (fresh / 'completed.json').is_file()
    assert json.loads((fresh / 'envelope.json').read_text()) == asdict(envelope)
    assert len(reports) == 1 and reports[0]['payload_type'] == 'D1_REPORT'
    assert reports[0]['message_id'] != wc._stable_id(envelope.message_id, 'output-delivery')
    census = host.inspect_run_quiescence('review-census', [source.parent.parent])
    row = next(row for row in census['inspections'] if Path(row['native_start_path']) == fresh / 'started.json')
    assert row['status'] == 'STOPPED', row
    # Repeat the exact invocation is read-only and cannot start another provider.
    monkeypatch.setattr(adapter.subprocess, 'Popen', lambda *_a, **_k: pytest.fail('repeat invoked native'))
    assert recovery.main() == 3
    assert len(reports) == 1


@pytest.mark.parametrize('damage', ['missing-endpoint', 'envelope-hash', 'manifest', 'live-writer'])
def test_cli_invalid_resume_is_zero_spawn_and_does_not_create_correction(tmp_path, monkeypatch, damage, capsys):
    adapter, recovery, host, source, envelope, identity = prepared(tmp_path, monkeypatch, damage)
    monkeypatch.setattr(adapter.subprocess, 'Popen', lambda *_a, **_k: pytest.fail('invalid resume launched native'))
    monkeypatch.setattr(adapter, '_discover_capabilities', lambda *_: pytest.fail('invalid resume probed'))
    assert recovery.main() == 4
    assert not (source / 'review-corrections').exists()


def test_existing_d1_cli_uses_original_handoff_only(tmp_path, monkeypatch, capsys):
    adapter, recovery, host, source, envelope, identity = prepared(tmp_path, monkeypatch, None)
    monkeypatch.setattr(adapter.subprocess, 'Popen', lambda *_a, **_k: pytest.fail('recorded D1 started native'))
    seen = []
    monkeypatch.setattr(host, 'complete_checker_handoff', lambda actual: seen.append(actual) or
        {'status': 'CHECKER_D1_RECORDED', 'verdict': 'PASS', 'handoff': {'status': 'CHECKER_HANDOFF_PENDING'}})
    assert recovery.main() == 3
    assert seen == [source]
    assert not (source / 'review-corrections').exists() and not (source / 'ocrv-result.json').exists()


def run_partial(tmp_path, monkeypatch, send):
    adapter, recovery, host, source, envelope, identity = prepared(tmp_path, monkeypatch)
    script = tmp_path / 'fake_native.py'
    script.write_text(FAKE_NATIVE)
    monkeypatch.setenv('OCRV_SLK_COMMAND_JSON', json.dumps([sys.executable, str(script)]))
    monkeypatch.setattr(adapter, '_discover_capabilities', lambda *_: {'invocations': []})
    monkeypatch.setattr(wc, '_run_json_command', send)
    assert recovery.main() == 3
    return adapter, recovery, host, source, source / 'review-corrections' / identity


def test_cli_repeat_retries_only_failed_public_report_suffix(tmp_path, monkeypatch, capsys):
    calls = []
    def send(_cmd, args, **_kwargs):
        calls.append(wc._read_object(Path(args[args.index('--envelope') + 1]), 'report'))
        return {'status': 'failed' if len(calls) == 1 else 'started'}
    adapter, recovery, host, source, fresh = run_partial(tmp_path, monkeypatch, send)
    assert json.loads(capsys.readouterr().out)['output_delivery']['status'] == 'OUTPUT_DELIVERY_UNCONFIRMED'
    native_before = {name: (fresh / name).read_bytes() for name in
        ('started.json', 'completed.json', 'ocrv-result.json', 'native-argv.json', 'resume-result.json')}
    monkeypatch.setattr(adapter.subprocess, 'Popen', lambda *_a, **_k: pytest.fail('report retry launched native'))
    assert recovery.main() == 3
    assert json.loads(capsys.readouterr().out)['output_delivery']['status'] == 'OUTPUT_DELIVERED'
    assert len(calls) == 2 and calls[0] == calls[1]
    assert all((fresh / name).read_bytes() == data for name, data in native_before.items())


def test_cli_crash_after_native_seal_retries_only_original_report_suffix(tmp_path, monkeypatch, capsys):
    adapter, recovery, host, source, envelope, identity = prepared(tmp_path, monkeypatch)
    script = tmp_path / 'fake_native.py'
    script.write_text(FAKE_NATIVE)
    monkeypatch.setenv('OCRV_SLK_COMMAND_JSON', json.dumps([sys.executable, str(script)]))
    monkeypatch.setattr(adapter, '_discover_capabilities', lambda *_: {'invocations': []})
    complete = host.complete
    def crash(_):
        raise SystemExit('isolated coordinator crash after native seal')
    monkeypatch.setattr(host, 'complete', crash)
    with pytest.raises(SystemExit, match='coordinator crash'):
        recovery.main()
    fresh = source / 'review-corrections' / identity
    assert (fresh / 'completed.json').is_file() and (fresh / 'ocrv-result.json').is_file()
    assert not (fresh / 'resume-result.json').exists()
    old = {path.relative_to(fresh): path.read_bytes() for path in fresh.rglob('*') if path.is_file()}
    monkeypatch.setattr(adapter.subprocess, 'Popen', lambda *_a, **_k: pytest.fail('suffix replay launched native'))
    monkeypatch.setattr(host, 'complete', complete)
    reports = []
    def send(_cmd, args, **_kwargs):
        reports.append(wc._read_object(Path(args[args.index('--envelope') + 1]), 'report'))
        return {'status': 'started'}
    monkeypatch.setattr(wc, '_run_json_command', send)
    assert recovery.main() == 3
    assert json.loads(capsys.readouterr().out)['output_delivery']['status'] == 'OUTPUT_DELIVERED'
    assert len(reports) == 1
    assert all((fresh / name).read_bytes() == data for name, data in old.items())


@pytest.mark.parametrize('damage', ['launcher-live', 'process-missing', 'index-changed'])
def test_correction_census_requires_both_bound_writers_stopped(tmp_path, monkeypatch, capsys, damage):
    adapter, recovery, host, source, fresh = run_partial(tmp_path, monkeypatch, lambda *_a, **_k: {'status': 'started'})
    from slk_transport import native_ocrv
    process_path = fresh / 'ocrv-native-process.json'
    if damage == 'process-missing':
        process_path.unlink()
    elif damage == 'index-changed':
        process = json.loads(process_path.read_text())
        Path(process['index_path']).write_text('{}')
    else:
        process = json.loads(process_path.read_text())
        launcher = process['launcher_process']
        process['process'] = {'pid': launcher['pid'] + 1, 'creation_time': launcher['creation_time']}
        process_path.write_text(json.dumps(process))
        def probe(pid, created):
            alive = pid == launcher['pid']
            return {'exists': alive, 'identity_matches': alive}
        monkeypatch.setattr(native_ocrv, 'process_probe', probe)
        monkeypatch.setattr('slk_transport.native_activity.process_probe', probe)
    census = host.inspect_run_quiescence('review-census', [source.parent.parent])
    row = next(row for row in census['inspections'] if Path(row['native_start_path']) == fresh / 'started.json')
    assert row['status'] == 'UNKNOWN', row
    assert census['status'] == 'NOT_QUIESCENT'


def test_correction_marker_tamper_blocks_cli_and_census(tmp_path, monkeypatch, capsys):
    adapter, recovery, host, source, fresh = run_partial(tmp_path, monkeypatch, lambda *_a, **_k: {'status': 'started'})
    marker = json.loads((fresh / 'ocrv-resume.json').read_text())
    marker['binding_sha256'] = '0' * 64
    (fresh / 'ocrv-resume.json').write_text(json.dumps(marker))
    monkeypatch.setattr(adapter.subprocess, 'Popen', lambda *_a, **_k: pytest.fail('tampered marker launched native'))
    assert recovery.main() == 4
    census = host.inspect_run_quiescence('review-census', [source.parent.parent])
    row = next(row for row in census['inspections'] if Path(row['native_start_path']) == fresh / 'started.json')
    assert row['status'] == 'UNKNOWN'
    assert 'historical Host reference' in row['reason']
    assert census['status'] == 'NOT_QUIESCENT'


def test_correction_census_reads_explicit_frozen_host_across_plan_change(tmp_path, monkeypatch, capsys):
    adapter, recovery, host, source, fresh = run_partial(tmp_path, monkeypatch, lambda *_a, **_k: {'status': 'started'})
    frozen = tmp_path / 'frozen-checker-host.json'
    frozen.write_bytes((tmp_path / 'binding.json').read_bytes())
    assert wc._sha256(frozen) == host.digest
    host.binding = {**host.binding, 'plan_revision': host.binding['plan_revision'] + 1}
    host.digest = 'f' * 64
    census = host.inspect_run_quiescence('review-census', [source.parent.parent],
        historical_host_refs=[{'path': str(frozen), 'sha256': wc._sha256(frozen)}])
    row = next(row for row in census['inspections'] if Path(row['native_start_path']) == fresh / 'started.json')
    assert row['status'] == 'STOPPED', row


@pytest.mark.parametrize('link_kind', ['is_symlink', 'is_junction'])
def test_census_never_descends_into_rejected_ocrv_link(tmp_path, monkeypatch, link_kind):
    host, source, envelope = prepared_host(tmp_path)
    child = source / 'review-corrections' / '11111111-1111-4111-8111-111111111111'
    (child / 'review-corrections').mkdir(parents=True)
    (child / 'envelope.json').write_text(json.dumps(asdict(envelope)))
    (child / 'ocrv-resume.json').write_text(json.dumps({'binding_sha256': host.digest}))
    monkeypatch.setattr(host, 'projection', lambda: {'runtime_snapshot': {'runtime_revision': 7}})
    original_check = getattr(Path, link_kind, lambda _path: False)
    monkeypatch.setattr(Path, link_kind, lambda path: path == child or original_check(path), raising=False)
    original_iterdir = Path.iterdir
    def guarded_iterdir(path):
        assert not path.is_relative_to(child), 'DESCENDED_INTO_REJECTED_LINK'
        return original_iterdir(path)
    monkeypatch.setattr(Path, 'iterdir', guarded_iterdir)
    census = host.inspect_run_quiescence('review', [source.parents[1]])
    row = next(row for row in census['inspections'] if Path(row['native_start_path']) == child / 'started.json')
    assert row['status'] == 'UNKNOWN'
    assert census['status'] == 'NOT_QUIESCENT'


@pytest.mark.parametrize('damage', ['wrong-session', 'changed-capacity', 'executor-live', 'query-denied'])
def test_authenticated_d1_cli_does_not_bypass_session_scope_or_writer_proof(tmp_path, monkeypatch, capsys, damage):
    adapter, recovery, host, source, envelope, identity = prepared(tmp_path, monkeypatch, None)
    from slk_transport import native_ocrv, native_activity
    if damage == 'wrong-session':
        sys.argv[sys.argv.index('--resume-session') + 1] = 'different-session'
    elif damage == 'changed-capacity':
        request = json.loads((source / 'ocrv-request.json').read_text())
        request['capacity']['max_tokens'] += 1
        (source / 'ocrv-request.json').write_text(json.dumps(request))
    elif damage == 'executor-live':
        import os
        path = source / 'ocrv-native-process.json'
        process = json.loads(path.read_text())
        process['process'] = {'pid': os.getpid(), 'creation_time': native_activity.process_creation_time(os.getpid())}
        path.write_text(json.dumps(process))
    else:
        def denied(*_):
            raise PermissionError('isolated process query denied')
        monkeypatch.setattr(native_ocrv, 'process_probe', denied)
    old = {path.relative_to(source): path.read_bytes() for path in source.rglob('*') if path.is_file()}
    monkeypatch.setattr(adapter.subprocess, 'Popen', lambda *_a, **_k: pytest.fail('invalid D1 reuse launched native'))
    monkeypatch.setattr(host, 'complete_checker_handoff', lambda *_: pytest.fail('unproven writer handed off'))
    assert recovery.main() == 4
    assert all((source / name).read_bytes() == data for name, data in old.items())
    assert not (source / 'ocrv-result.json').exists() and not (source / 'review-corrections').exists()


def observation_scope(source, monkeypatch):
    from test_worker_completion import runtime_projection
    endpoint = json.loads((source / 'endpoint.json').read_text())
    envelope = json.loads((source / 'envelope.json').read_text())
    projection = runtime_projection(token_owner=endpoint['role_instance_id'])
    projection['runtime_snapshot'].update(latest_message_id=envelope['message_id'], token_sequence=envelope['token_sequence'])
    projection['roles'] = [{'role': 'checker', 'role_instance_id': endpoint['role_instance_id']}]
    projection['go_nodes'] = [{'go_id': envelope['go_id'], 'cell_nodes': [{'cell_id': envelope['cell_id'], 'attempt': 1}]}]
    event = projection['events'][0]
    event.update(go_id=envelope['go_id'], cell_id=envelope['cell_id'], author_role_instance_id=envelope['sender_role_instance_id'])
    event['details_json'] = json.dumps({'message_id': envelope['message_id'],
        'start_evidence_sha256': wc._sha256(source / 'started.json'),
        'endpoint_sha256': wc._sha256(source / 'endpoint.json'), 'envelope_sha256': wc._sha256(source / 'envelope.json')})
    monkeypatch.setattr(wc, '_default_load_current_projection', lambda *_a, **_k: projection)
    return projection


@pytest.mark.parametrize('state', ['active', 'completed', 'pending'])
def test_real_cli_resume_is_the_observed_checker_and_cycle_consumer_agrees(tmp_path, monkeypatch, capsys, state):
    adapter, recovery, host, source, fresh = run_partial(tmp_path, monkeypatch, lambda *_a, **_k: {'status': 'started'})
    from slk_transport import native_activity as native, native_ocrv, overwatcher_admin as admin
    from test_worker_resume_observation import cycle_for
    projection = observation_scope(source, monkeypatch)
    if state in {'active', 'pending'}:
        (fresh / 'completed.json').unlink()
    if state == 'pending':
        (fresh / 'started.json').unlink()
    elif state == 'active':
        binding = json.loads((fresh / 'ocrv-session-binding.json').read_text())
        session = Path(binding['session_path'])
        session.write_text(''.join(line for line in session.read_text().splitlines(keepends=True) if 'session_end' not in line))
        child_pid = json.loads((fresh / 'started.json').read_text())['process']['pid']
        monkeypatch.setattr(native_ocrv, 'process_probe', lambda pid, _: {'exists': pid == child_pid, 'identity_matches': pid == child_pid})
    old = {path: path.read_bytes() for path in source.rglob('*') if path.is_file()}
    query = native.collect_overwatch_scope(source / 'started.json', run_id='RUN-A', state_command=['slk-state'])
    assert query['native_activity']['status'] == {'active': 'ACTIVE', 'completed': 'COMPLETED', 'pending': 'UNKNOWN'}[state], query
    assert query['native_resume']['invocation_id'] == fresh.name
    assert query['native_resume']['native_start_path'] == str(fresh / 'started.json')
    assert query['native_start_path'] == str((source / 'started.json').resolve())
    assert query['native_start_sha256'] == wc._sha256(source / 'started.json')
    assert query['worker_completion'] is None
    admin._verify_cycle(cycle_for(tmp_path, source, projection, query), 'RUN-A', ['slk-state'])
    assert all(path.read_bytes() == data for path, data in old.items())


@pytest.mark.parametrize('damage', ['marker', 'multiple-leaves', 'empty-claim', 'missing-marker', 'sealed-live-writer', 'query-denied'])
def test_checker_observation_does_not_fall_back_to_original_after_invalid_resume(tmp_path, monkeypatch, capsys, damage):
    adapter, recovery, host, source, fresh = run_partial(tmp_path, monkeypatch, lambda *_a, **_k: {'status': 'started'})
    from slk_transport import native_activity as native, overwatcher_admin as admin
    from test_worker_resume_observation import cycle_for
    projection = observation_scope(source, monkeypatch)
    if damage == 'marker':
        marker = json.loads((fresh / 'ocrv-resume.json').read_text())
        marker['original_source_sha256'] = '0' * 64
        (fresh / 'ocrv-resume.json').write_text(json.dumps(marker))
    elif damage == 'multiple-leaves':
        (fresh.parent / str(uuid.uuid4())).mkdir()
    elif damage == 'empty-claim':
        # Observe an empty claim left by a coordinator before creating its child.
        fresh.rename(tmp_path / 'isolated-child-outside-claim')
    elif damage == 'missing-marker':
        (fresh / 'ocrv-resume.json').unlink()
    elif damage == 'sealed-live-writer':
        from slk_transport import native_ocrv
        child_pid = json.loads((fresh / 'started.json').read_text())['process']['pid']
        monkeypatch.setattr(native_ocrv, 'process_probe', lambda pid, _: {'exists': pid == child_pid, 'identity_matches': pid == child_pid})
    else:
        from slk_transport import native_ocrv
        def denied(*_):
            raise PermissionError('isolated native process query denied')
        monkeypatch.setattr(native_ocrv, 'process_probe', denied)
    query = native.collect_overwatch_scope(source / 'started.json', run_id='RUN-A', state_command=['slk-state'])
    assert query['native_activity']['status'] == 'UNKNOWN'
    assert 'NATIVE_RESUME_QUERY_UNAVAILABLE' in query['native_activity']['error']
    assert query['native_start_sha256'] == wc._sha256(source / 'started.json')
    admin._verify_cycle(cycle_for(tmp_path, source, projection, query), 'RUN-A', ['slk-state'])


@pytest.mark.parametrize('change', ['clear', 'different-error', 'recovered-selector', 'forged-metadata'])
def test_cycle_rejects_nonmatching_resume_failure_or_a_clear_claim(tmp_path, monkeypatch, capsys, change):
    adapter, recovery, host, source, fresh = run_partial(tmp_path, monkeypatch, lambda *_a, **_k: {'status': 'started'})
    from slk_transport import native_activity as native, overwatcher_admin as admin
    from test_worker_resume_observation import cycle_for
    projection = observation_scope(source, monkeypatch)
    marker_path = fresh / 'ocrv-resume.json'
    marker_bytes = marker_path.read_bytes()
    marker_path.unlink()
    query = native.collect_overwatch_scope(source / 'started.json', run_id='RUN-A', state_command=['slk-state'])
    assert query['native_activity']['status'] == 'UNKNOWN'
    if change == 'different-error':
        marker_path.write_text('{}')
    elif change == 'recovered-selector':
        marker_path.write_bytes(marker_bytes)
    elif change == 'forged-metadata':
        query['native_resume'] = {'invocation_id': fresh.name}
    cycle = cycle_for(tmp_path, source, projection, query)
    if change == 'clear':
        cycle.update(checklist={'active_session': 'CLEAR'}, anomaly_codes=[])
    with pytest.raises(ValueError, match='OVERWATCHER_CYCLE_EVIDENCE_INVALID'):
        admin._verify_cycle(cycle, 'RUN-A', ['slk-state'])
