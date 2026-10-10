"""Real headless local processes/MCP; no model, state DB or product Run."""
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
from types import SimpleNamespace
import zipfile

import pytest

from test_ocrv_preflight import _request

ROOT = Path(__file__).resolve().parents[2]


def _load_adapter():
    path = ROOT / 'integrations/ocrv/slk_checker_adapter.py'
    spec = importlib.util.spec_from_file_location('ocrv_natural_exit', path)
    adapter = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(adapter)
    return adapter


def _natural_exit(tmp_path, monkeypatch, verdict='PASS', exit_code=0, damage=None,
                  timeout_mode=None, post_damage=False, stream_failure=None):
    """Force wait's natural-return branch; keep receipt validation and drains real."""
    adapter = _load_adapter()
    request, output, _ = _request(tmp_path)
    source = tmp_path / 'source'
    source.mkdir()
    receipt = source / 'native-start.received.json'
    context = {'adapter': 'ocrv-checker', 'run_id': 'RUN-PREFLIGHT-A', 'cell_id': 'CELL-001',
        'message_id': 'message-A', 'request_sha256': 'b' * 64,
        'native_request_sha256': hashlib.sha256(request.read_bytes()).hexdigest()}
    monkeypatch.setenv('SLK_NATIVE_START_RECEIPT', str(receipt))
    monkeypatch.setenv('SLK_NATIVE_START_CONTEXT', json.dumps(context))
    monkeypatch.setattr(adapter, '_discover_capabilities', lambda *_: {'invocations': []})
    close = adapter._close_completed_review
    close_calls = []

    def close_once(process, *args):
        close_calls.append(process.pid)
        if timeout_mode == 'already-exited':
            return close(process, *args)
        if timeout_mode == 'denied':
            assert process.poll() is None
            raise OSError('original review termination denied')
        if timeout_mode == 'closed':
            return
        pytest.fail('natural exit must not close a dead process')

    monkeypatch.setattr(adapter, '_close_completed_review', close_once)

    class ExitedProcess:
        pid = os.getpid()
        stdout = io.BytesIO(b'original stdout before natural exit\n')
        stderr = io.BytesIO(b'original stderr before natural exit\n')
        waits = 0

        def poll(self):
            return None if timeout_mode == 'denied' and self.waits < 3 else exit_code

        def wait(self, timeout):
            self.waits += 1
            if self.waits > 1:
                if self.waits == 2 and post_damage:
                    completion = tmp_path / 'review-completed.json'
                    completed = json.loads(completion.read_text(encoding='utf-8'))
                    completed['native_task_id'] = 'tampered-after-timeout'
                    completion.write_text(json.dumps(completed), encoding='utf-8')
                if timeout_mode == 'denied' and self.waits == 2:
                    raise subprocess.TimeoutExpired('fake native review', timeout)
                return exit_code
            decision = source / 'role-host/checker-decision.json'
            decision.parent.mkdir()
            decision.write_text(json.dumps({'source_message_id': context['message_id'],
                'native_task_id': 'native-A', 'verdict': verdict}), encoding='utf-8')
            completed = {**context, 'schema_version': 'slk.ocrv-completion/v1',
                'native_task_id': 'native-A', 'native_start_sha256': adapter._sha256(receipt),
                'decision_path': str(decision), 'decision_sha256': adapter._sha256(decision),
                'verdict': verdict, 'review_process': {'pid': self.pid,
                    'creation_time': adapter._process_creation_time(self.pid)}}
            if damage == 'invocation':
                completed['native_task_id'] = 'other-native'
            elif damage == 'start-hash':
                completed['native_start_sha256'] = '0' * 64
            elif damage == 'decision-hash':
                completed['decision_sha256'] = '0' * 64
            completion = tmp_path / 'review-completed.json'
            if damage == 'utf8':
                completion.write_bytes(b'\xff')
            elif damage != 'missing':
                completion.write_text('invalid JSON' if damage == 'json' else json.dumps(completed),
                                      encoding='utf-8')
            # A raw report/finding or rc0 cannot replace the bound explicit decision.
            (tmp_path / 'ocrv-review.json').write_text(json.dumps({'status': 'partial',
                'verdict': 'PASS', 'comments': [{'severity': 'LOW', 'message': 'original finding'}]}),
                encoding='utf-8')
            if timeout_mode is not None:
                raise subprocess.TimeoutExpired('fake native review', timeout)
            return exit_code  # No TimeoutExpired in the natural-only cases.

    process = ExitedProcess()
    original_open = Path.open

    class FailingSink:
        def __init__(self, saved):
            self.saved = saved

        def write(self, value):
            if stream_failure == 'write':
                self.saved.write(value[:9])
                raise OSError('isolated original stream write unavailable')
            return self.saved.write(value)

        def flush(self):
            self.saved.flush()
            if stream_failure == 'flush':
                raise OSError('isolated original stream flush unavailable')

        def close(self):
            self.saved.close()

        def __enter__(self):
            return self

        def __exit__(self, *_):
            self.close()

    def open_original_stream(path, mode='r', *args, **kwargs):
        if path.name == 'ocrv.stdout.txt' and mode == 'wb':
            if stream_failure == 'open':
                raise OSError('isolated original stream open unavailable')
            return FailingSink(original_open(path, mode, *args, **kwargs))
        return original_open(path, mode, *args, **kwargs)

    class FailingReader(io.BytesIO):
        def read1(self, size):
            if self.tell():
                raise OSError('isolated original stream read unavailable')
            return super().read1(9)

    if stream_failure in ('open', 'write', 'flush'):
        monkeypatch.setattr(Path, 'open', open_original_stream)
    if stream_failure == 'read':
        process.stdout = FailingReader(b'original stdout before natural exit\n')
    authenticate = adapter._completed_decision
    auth_after_saved_logs = []

    def authenticate_original(*args):
        saved = all((tmp_path / name).is_file() for name in ('ocrv.stdout.txt', 'ocrv.stderr.txt'))
        auth_after_saved_logs.append(saved)
        return authenticate(*args)

    monkeypatch.setattr(adapter, '_completed_decision', authenticate_original)
    monkeypatch.setattr(adapter.subprocess, 'Popen', lambda *_args, **_kwargs: process)
    status = adapter.run(request, output, invocation_override='native-A')
    assert auth_after_saved_logs[-1] is (stream_failure != 'open')
    assert len(close_calls) == (1 if timeout_mode is not None and damage is None else 0)
    assert process.stdout.closed and process.stderr.closed
    result = json.loads(output.read_text(encoding='utf-8'))
    assert result['review']['exit_code'] == exit_code
    stdout = Path(result['artifacts']['stdout'])
    if stream_failure == 'open':
        assert not stdout.exists()
    else:
        expected = 'original ' if stream_failure in ('write', 'read') else 'original stdout before natural exit\n'
        assert stdout.read_text(encoding='utf-8') == expected
    assert Path(result['artifacts']['stderr']).read_text(encoding='utf-8') == 'original stderr before natural exit\n'
    assert json.loads(Path(result['artifacts']['raw_review']).read_text(encoding='utf-8'))['status'] == 'partial'
    assert result['findings'] == [{'severity': 'LOW', 'message': 'original finding'}]
    return status, result


@pytest.mark.parametrize('stage', ['open', 'write', 'flush', 'read'])
@pytest.mark.parametrize('exit_code', [0, 9])
def test_stream_failure_is_reported_without_erasing_authenticated_d1(tmp_path, monkeypatch, stage, exit_code):
    status, result = _natural_exit(tmp_path, monkeypatch, verdict='FAIL', exit_code=exit_code,
                                   stream_failure=stage)
    assert status != 0
    assert result['verdict'] == 'FAIL' and result['verdict_source'] == 'CHECKER_EXPLICIT'
    assert result['review']['exit_code'] == exit_code
    assert result['review']['closure_reason'] == 'EXPLICIT_D1_COMPLETED'
    assert f'ocrv.stdout.txt {stage}' in result['review']['closure_error']
    assert f'isolated original stream {stage} unavailable' in result['review']['closure_error']
    completion = json.loads((tmp_path / 'review-completed.json').read_text())
    assert completion['decision_sha256'] == hashlib.sha256(Path(completion['decision_path']).read_bytes()).hexdigest()
    activity = json.loads((tmp_path / 'source/native-activity.json').read_text())
    assert activity['status'] == 'COMPLETED'  # original native outcome, not adapter IO success
    assert activity['error'] == 'OCRV_STREAM_FAILED'


@pytest.mark.parametrize('verdict', ['PASS', 'FAIL', 'INCOMPLETE'])
@pytest.mark.parametrize('exit_code', [0, 9])
def test_natural_exit_validates_explicit_completion_without_timeout(tmp_path, monkeypatch, verdict, exit_code):
    status, result = _natural_exit(tmp_path, monkeypatch, verdict, exit_code)
    assert status == 0
    assert result['verdict'] == verdict
    assert result['verdict_source'] == 'CHECKER_EXPLICIT'
    assert result['review']['closure_reason'] == 'EXPLICIT_D1_COMPLETED'
    assert result['review']['closure_error'] is None


@pytest.mark.parametrize('stage', ['open', 'write', 'flush'])
def test_failed_sink_still_drains_a_real_native_pipe_without_retry(tmp_path, monkeypatch, stage):
    adapter = _load_adapter()
    request, output, _ = _request(tmp_path)
    monkeypatch.delenv('SLK_NATIVE_START_RECEIPT', raising=False)
    monkeypatch.delenv('SLK_NATIVE_START_CONTEXT', raising=False)
    monkeypatch.setattr(adapter, '_discover_capabilities', lambda *_: {'invocations': []})
    monkeypatch.setattr(adapter, '_review_args', lambda *_: [sys.executable, '-u', '-c',
        "import sys; sys.stdout.buffer.write(b'x'*(2*1024*1024)); sys.stdout.buffer.flush(); "
        "sys.stderr.buffer.write(b'original untouched stderr'); sys.stderr.buffer.flush()"])
    original_open, popen = Path.open, adapter.subprocess.Popen
    processes, operations = [], []

    class Sink:
        def __init__(self, saved):
            self.saved = saved

        def write(self, value):
            operations.append('write')
            if stage == 'write':
                self.saved.write(value[:9])
                raise OSError('isolated sink write failed')
            return self.saved.write(value)

        def flush(self):
            operations.append('flush')
            self.saved.flush()
            if stage == 'flush':
                raise OSError('isolated sink flush failed')

        def close(self):
            self.saved.close()

    def open_sink(path, mode='r', *args, **kwargs):
        if path.name == 'ocrv.stdout.txt' and mode == 'wb':
            operations.append('open')
            if stage == 'open':
                raise OSError('isolated sink open failed')
            return Sink(original_open(path, mode, *args, **kwargs))
        return original_open(path, mode, *args, **kwargs)

    def start(*args, **kwargs):
        process = popen(*args, **kwargs)
        processes.append(process)
        return process

    monkeypatch.setattr(Path, 'open', open_sink)
    monkeypatch.setattr(adapter.subprocess, 'Popen', start)
    outcome = []
    running = threading.Thread(target=lambda: outcome.append(adapter.run(request, output, invocation_override='stream-test')))
    running.start()
    try:
        running.join(8)
        assert not running.is_alive(), 'a failed sink must not leave a full native pipe'
    finally:
        for process in processes:
            if process.poll() is None:
                process.terminate()  # only this test's exact local fake process
                process.wait(timeout=5)
        running.join(5)
    result = json.loads(output.read_text())
    assert outcome == [1] and result['review']['exit_code'] == 0
    assert f'ocrv.stdout.txt {stage}' in result['review']['closure_error']
    assert (tmp_path / 'ocrv.stderr.txt').read_bytes() == b'original untouched stderr'
    assert operations.count(stage) == 1
    if stage != 'open':
        saved = (tmp_path / 'ocrv.stdout.txt').read_bytes()
        assert saved and saved == b'x' * len(saved)


def test_ocrv_source_binds_marker_to_original_invocation_without_claiming_native_pid(tmp_path, monkeypatch):
    _natural_exit(tmp_path, monkeypatch)
    start = json.loads((tmp_path / 'source/native-start.received.json').read_text())
    assert start['native_task']['kind'] == 'ocrv-invocation'
    source = json.loads((tmp_path / 'source/ocrv-native-source.json').read_text())
    assert source['native_start_sha256'] == hashlib.sha256((tmp_path / 'source/native-start.received.json').read_bytes()).hexdigest()
    background = Path(source['background_path']).read_text(encoding='utf-8')
    assert background.splitlines()[0] == source['marker']
    assert 'native-A' in source['marker'] and start['native_request_sha256'] in source['marker']
    assert source['invocation_id'] == start['native_task']['id']
    assert 'native_pid' not in source


def test_ocrv_capability_names_only_public_native_session_events():
    value = json.loads((ROOT / 'integrations/ocrv/slk-native-activity-capabilities.json').read_text())
    assert value['native_events'] == ['session_start', 'tool_call', 'session_end']


def test_ocrv_wrapper_observes_both_streams_without_claiming_session_activity(tmp_path, monkeypatch):
    _natural_exit(tmp_path, monkeypatch)
    activity = json.loads((tmp_path / 'source/native-activity.json').read_text())
    tail = activity['last_event']['tail']
    assert {event['kind'] for event in tail} == {'OCRV_PROCESS_STARTED', 'OCRV_STDOUT', 'OCRV_PROGRESS', 'OCRV_PROCESS_EXITED'}
    assert [event['sequence'] for event in tail] == [0, 1, 2, 3]
    assert activity['native_task_id'] == 'native-A'


@pytest.mark.parametrize('damage', ['missing', 'json', 'utf8', 'invocation', 'start-hash', 'decision-hash'])
def test_natural_rc0_without_valid_completion_is_not_d1(tmp_path, monkeypatch, damage):
    status, result = _natural_exit(tmp_path, monkeypatch, damage=damage)
    assert status == 0  # Preserve natural rc0 as a process fact, not a D1 verdict.
    assert result['verdict'] is None
    assert result['verdict_source'] is None
    assert result['review']['closure_reason'] is None
    assert result['review']['closure_error']


@pytest.mark.parametrize('verdict', ['PASS', 'FAIL', 'INCOMPLETE'])
def test_timeout_then_exited_original_retains_authenticated_d1(tmp_path, monkeypatch, verdict):
    status, result = _natural_exit(tmp_path, monkeypatch, verdict, 9, timeout_mode='already-exited')
    assert status == 0
    assert result['verdict'] == verdict
    assert result['verdict_source'] == 'CHECKER_EXPLICIT'
    assert result['review']['closure_reason'] == 'EXPLICIT_D1_COMPLETED'
    assert 'not a live owned process' in result['review']['closure_error']


@pytest.mark.parametrize('verdict', ['PASS', 'FAIL', 'INCOMPLETE'])
def test_live_cleanup_error_does_not_erase_d1_or_retry_cleanup(tmp_path, monkeypatch, verdict):
    status, result = _natural_exit(tmp_path, monkeypatch, verdict, 9, timeout_mode='denied')
    assert status == 0
    assert result['verdict'] == verdict
    assert result['verdict_source'] == 'CHECKER_EXPLICIT'
    assert result['review']['closure_reason'] == 'EXPLICIT_D1_COMPLETED'
    assert 'original review termination denied' in result['review']['closure_error']


@pytest.mark.parametrize('ending', ['\n', ''])
def test_denied_cleanup_exposes_original_streams_and_failure_before_native_exit(tmp_path, monkeypatch, ending):
    adapter = _load_adapter()
    request, output, _ = _request(tmp_path)
    source = tmp_path / 'source'
    source.mkdir()
    receipt = source / 'native-start.received.json'
    context = {'adapter': 'ocrv-checker', 'run_id': 'RUN-PREFLIGHT-A', 'cell_id': 'CELL-001',
        'message_id': 'message-A', 'request_sha256': 'b' * 64,
        'native_request_sha256': hashlib.sha256(request.read_bytes()).hexdigest()}
    monkeypatch.setenv('SLK_NATIVE_START_RECEIPT', str(receipt))
    monkeypatch.setenv('SLK_NATIVE_START_CONTEXT', json.dumps(context))
    monkeypatch.setattr(adapter, '_discover_capabilities', lambda *_: {'invocations': []})
    release = tmp_path / 'release'
    command = [sys.executable, '-u', '-c',
        f"import pathlib,sys,time; print('original stdout',end={ending!r},flush=True); "
        f"print('original stderr',end={ending!r},file=sys.stderr,flush=True); "
        f"p=pathlib.Path({str(release)!r}); "
        "exec('while not p.exists(): time.sleep(0.02)'); sys.exit(9)"]
    monkeypatch.setattr(adapter, '_review_args', lambda *_: command)
    denied = threading.Event()
    streams_saved = threading.Event()
    diagnostic_saved = threading.Event()
    saved_kinds = set()
    write_json = adapter._write_json_atomic

    def observe_saved(path, value):
        write_json(path, value)
        if path.name == 'native-activity.json':
            saved_kinds.add(value.get('last_event', {}).get('kind'))
            if {'OCRV_STDOUT', 'OCRV_PROGRESS'} <= saved_kinds:
                streams_saved.set()
            if value.get('error') == 'OCRV_CLEANUP_FAILED':
                diagnostic_saved.set()

    monkeypatch.setattr(adapter, '_write_json_atomic', observe_saved)
    calls = []

    def deny(process, *_):
        assert process.poll() is None
        calls.append(process.pid)
        denied.set()
        raise OSError('original review termination denied')

    monkeypatch.setattr(adapter, '_close_completed_review', deny)
    outcome = []
    running = threading.Thread(target=lambda: outcome.append(adapter.run(request, output, invocation_override='native-A')))
    running.start()
    try:
        deadline = time.monotonic() + 8
        while not receipt.is_file() and time.monotonic() < deadline:
            time.sleep(0.01)
        start = json.loads(receipt.read_text())
        assert streams_saved.wait(8), 'flushed partial native output must not wait for exit'
        decision = source / 'role-host' / 'checker-decision.json'
        decision.parent.mkdir()
        decision.write_text(json.dumps({'source_message_id': context['message_id'],
            'native_task_id': 'native-A', 'verdict': 'FAIL'}))
        completion = {**context, 'schema_version': 'slk.ocrv-completion/v1', 'native_task_id': 'native-A',
            'native_start_sha256': adapter._sha256(receipt), 'decision_path': str(decision),
            'decision_sha256': adapter._sha256(decision), 'verdict': 'FAIL', 'review_process': start['process']}
        (tmp_path / 'review-completed.json').write_text(json.dumps(completion))
        assert denied.wait(8)
        assert diagnostic_saved.wait(8)
        activity = json.loads((source / 'native-activity.json').read_text())
        assert running.is_alive() and not output.exists()
        assert (tmp_path / 'ocrv.stdout.txt').read_text() == 'original stdout' + ending
        assert (tmp_path / 'ocrv.stderr.txt').read_text() == 'original stderr' + ending
        assert activity['status'] == 'RUNNING' and activity['error'] == 'OCRV_CLEANUP_FAILED'
        # Final authentication must still reject a changed decision after denied cleanup.
        completion['native_task_id'] = 'other-invocation'
        (tmp_path / 'review-completed.json').write_text(json.dumps(completion))
    finally:
        release.touch()
        running.join(8)
    assert not running.is_alive() and len(calls) == 1
    result = json.loads(output.read_text())
    assert outcome == [9] and result['review']['exit_code'] == 9
    assert result['verdict'] is None and 'termination denied' in result['review']['closure_error']


def test_owned_cleanup_ancestry_has_no_depth_cap_and_rejects_cycles(monkeypatch):
    adapter = _load_adapter()
    killed = []
    monkeypatch.setattr(adapter, 'os', SimpleNamespace(name='posix', kill=lambda *args: killed.append(args)))
    monkeypatch.setattr(adapter, '_process_creation_time', lambda _: 'original-time')
    parents = {pid: pid - 1 for pid in range(2, 70)}
    monkeypatch.setattr(adapter, '_process_parents', lambda: parents)
    process = SimpleNamespace(pid=1, poll=lambda: None)
    completed = {'review_process': {'pid': 69, 'creation_time': 'original-time'}}
    adapter._close_completed_review(process, completed, {'creation_time': 'original-time'})
    assert killed == [(69, 15)]
    parents[2] = 69
    with pytest.raises(adapter.RequestError, match='descendant'):
        adapter._close_completed_review(process, completed, {'creation_time': 'original-time'})
    assert killed == [(69, 15)]


@pytest.mark.parametrize('timeout_mode', ['already-exited', 'denied', 'closed'])
def test_timeout_completion_is_reauthenticated_after_drain(tmp_path, monkeypatch, timeout_mode):
    status, result = _natural_exit(tmp_path, monkeypatch, exit_code=9,
                                  timeout_mode=timeout_mode, post_damage=True)
    assert status == 9
    assert result['verdict'] is None
    assert result['verdict_source'] is None
    assert result['review']['closure_reason'] is None
    assert 'does not bind this native invocation' in result['review']['closure_error']
    if timeout_mode == 'denied':
        assert 'original review termination denied' in result['review']['closure_error']


@pytest.mark.parametrize('damage', ['missing', 'json', 'utf8', 'invocation', 'start-hash', 'decision-hash'])
def test_timeout_without_valid_completion_never_closes_or_decides(tmp_path, monkeypatch, damage):
    status, result = _natural_exit(tmp_path, monkeypatch, exit_code=9,
                                  damage=damage, timeout_mode='already-exited')
    assert status == 9
    assert result['verdict'] is None
    assert result['verdict_source'] is None
    assert result['review']['closure_reason'] is None
    assert result['review']['closure_error']


@pytest.mark.parametrize('natural_exit', [False, True])
@pytest.mark.parametrize('wrapped', [False, True])
@pytest.mark.parametrize('verdict', ['PASS', 'FAIL', 'INCOMPLETE'])
def test_explicit_d1_closes_only_original_review_and_keeps_successor_alive(
    tmp_path, monkeypatch, wrapped, verdict, natural_exit,
):
    request, output, _ = _request(tmp_path)
    source = tmp_path / 'source'
    source.mkdir()
    package = tmp_path / 'fake-transport.pyz'
    host_source = '''import hashlib, json, os, subprocess, sys
from pathlib import Path
class Host:
    def submit_checker_decision(self, source, verdict, message):
        receipt=json.loads((source/'native-start.received.json').read_text())
        decision=source/'role-host'/'checker-decision.json'
        decision.parent.mkdir()
        decision.write_text(json.dumps({'source_message_id':receipt['message_id'],
            'native_task_id':receipt['native_task']['id'], 'verdict':verdict}))
        worker=subprocess.Popen([sys.executable,'-c','import time; time.sleep(20)'],
            stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
            creationflags=(subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0))
        (source/'successor-pid.txt').write_text(str(worker.pid))
        return {'status':'CHECKER_D1_RECORDED','verdict':verdict,'decision_path':str(decision),
                'handoff':{'status':'OWNED_HANDOFF_COMMITTED'}}
def load_role_host(endpoint): return Host()
'''
    with zipfile.ZipFile(package, 'w') as archive:
        archive.writestr('slk_transport/__init__.py', '')
        archive.writestr('slk_transport/role_host.py', host_source)
    (source / 'endpoint.json').write_text('{}', encoding='utf-8')
    environment = os.environ.copy()
    configuration = {'OCRV_SLK_COMMAND_JSON': json.dumps([sys.executable,
        str(Path(__file__).with_name('fake_ocrv_lifecycle.py')), *(['--wrap'] if wrapped else []),
        *(['--natural-exit'] if natural_exit else [])]),
        'OCRV_SLK_RUNTIME_ROOT': str(tmp_path / 'runtime'),
        'SLK_NATIVE_START_RECEIPT': str(source / 'native-start.received.json'),
        'SLK_NATIVE_START_CONTEXT': json.dumps({'adapter': 'ocrv-checker', 'run_id': 'RUN-PREFLIGHT-A',
            'cell_id': 'CELL-001', 'message_id': 'message-A', 'request_sha256': 'b' * 64,
            'native_request_sha256': hashlib.sha256(request.read_bytes()).hexdigest()}),
        'FAKE_VERDICT': verdict,
        'FAKE_CHECKER_BRIDGE': str(ROOT / 'integrations/ocrv/slk_checker_decision.py'),
        'FAKE_CHECKER_TRANSPORT': str(package)}
    environment.update(configuration)
    try:
        if natural_exit:
            adapter = _load_adapter()
            for key, value in configuration.items():
                monkeypatch.setenv(key, value)
            monkeypatch.setattr(adapter, '_discover_capabilities', lambda *_: {'invocations': []})
            popen = adapter.subprocess.Popen

            def start(*args, **kwargs):
                process = popen(*args, **kwargs)
                wait = process.wait
                # The real native process exits, but this test must never poll through TimeoutExpired.
                process.wait = lambda timeout=None: wait(timeout=12)
                return process

            monkeypatch.setattr(adapter.subprocess, 'Popen', start)
            assert adapter.run(request, output) == 0
        else:
            completed = subprocess.run([sys.executable, '-B', str(ROOT / 'integrations/ocrv/slk_checker_adapter.py'),
                '--request', str(request), '--output', str(output)], env=environment, capture_output=True,
                text=True, encoding='utf-8', timeout=12,
                creationflags=(subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0))
            assert completed.returncode == 0, completed.stderr
        result = json.loads(output.read_text(encoding='utf-8'))
        observed_process = json.loads((source / 'ocrv-native-process.json').read_text(encoding='utf-8'))
        native_start = json.loads((source / 'native-start.received.json').read_text(encoding='utf-8'))
        assert observed_process['native_start_sha256'] == hashlib.sha256((source / 'native-start.received.json').read_bytes()).hexdigest()
        assert observed_process['launcher_process'] == native_start['process']
        if wrapped:
            assert observed_process['process']['pid'] != native_start['process']['pid']
        assert result['verdict'] == verdict
        assert result['review']['closure_reason'] == 'EXPLICIT_D1_COMPLETED'
        assert result['review']['exit_code'] != 0  # do not invent a natural OCRV exit
        if natural_exit:
            assert result['review']['exit_code'] == 9
        assert 'partial original native log' in Path(result['artifacts']['stderr']).read_text(encoding='utf-8')
        # The downstream process was launched inside the MCP action. Tree-kill would wrongly kill it.
        if os.name == 'nt':
            import ctypes
            kernel = ctypes.WinDLL('kernel32', use_last_error=True)
            kernel.OpenProcess.restype = ctypes.c_void_p
            kernel.GetExitCodeProcess.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
            kernel.CloseHandle.argtypes = [ctypes.c_void_p]
            handle = kernel.OpenProcess(0x1000, False, int((source / 'successor-pid.txt').read_text()))
            code = ctypes.c_ulong()
            assert handle and kernel.GetExitCodeProcess(handle, ctypes.byref(code)) and code.value == 259
            kernel.CloseHandle(handle)
        else:
            os.kill(int((source / 'successor-pid.txt').read_text()), 0)
    finally:
        pid_file = source / 'successor-pid.txt'
        if pid_file.is_file():
            try:
                os.kill(int(pid_file.read_text()), 15)
            except OSError:
                pass
