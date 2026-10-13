"""Retired implicit review recovery must be an inert, explicit rejection."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


@pytest.mark.parametrize('supplement', [False, True])
def test_native_resume_rejects_unbound_source_before_any_spawn(tmp_path, monkeypatch, supplement):
    from test_ocrv_materials import load
    from test_ocrv_preflight import _request
    adapter = load('slk_checker_adapter.py')
    request, output, _ = _request(tmp_path)
    monkeypatch.setenv('OCRV_SLK_RUNTIME_ROOT', str(tmp_path / 'runtime'))
    monkeypatch.delenv('SLK_NATIVE_START_RECEIPT', raising=False)
    monkeypatch.delenv('SLK_NATIVE_START_CONTEXT', raising=False)
    monkeypatch.setattr(adapter.subprocess, 'Popen', lambda *_a, **_k: pytest.fail('invalid resume spawned native'))
    monkeypatch.setattr(adapter, '_discover_capabilities', lambda *_: pytest.fail('invalid resume spawned probe'))
    with pytest.raises(adapter.RequestError, match='bound original'):
        adapter.run(request, output, resume_session='original-session',
                    background_override=request if supplement else None)


def test_authenticated_d1_without_sealed_result_does_not_manufacture_output(tmp_path, monkeypatch):
    from test_ocrv_materials import load
    from test_ocrv_preflight import _request
    adapter = load('slk_checker_adapter.py')
    request, output, _ = _request(tmp_path)
    monkeypatch.setenv('OCRV_SLK_RUNTIME_ROOT', str(tmp_path / 'runtime'))
    monkeypatch.delenv('SLK_NATIVE_START_RECEIPT', raising=False)
    monkeypatch.delenv('SLK_NATIVE_START_CONTEXT', raising=False)
    decision = {'verdict': 'FAIL', 'message': 'original public decision', 'native_task_id': 'original',
                'path': str(tmp_path / 'decision.json'), 'sha256': 'a' * 64}
    monkeypatch.setattr(adapter, '_resume_preflight', lambda *_: decision)
    monkeypatch.setattr(adapter.subprocess, 'Popen', lambda *_a, **_k: pytest.fail('authenticated D1 spawned model'))
    monkeypatch.setattr(adapter, '_discover_capabilities', lambda *_: pytest.fail('authenticated D1 spawned probe'))
    with pytest.raises(adapter.RequestError, match='CHECKER_D1_RECORDED'):
        adapter.run(request, output, resume_session='original-session')
    assert not output.exists()

ROOT = Path(__file__).resolve().parents[2]

@pytest.mark.parametrize("operation", ["--slk-worker-recovery", "--slk-resume-incomplete",
    "--slk-existing-terminal", "--slk-committed-terminal", "--slk-terminal-budget"])
def test_retired_launcher_cannot_resume_review_or_mutate_history(tmp_path, operation):
    source = tmp_path/"original.json"
    source.write_bytes(b'original non-JSON report\r\n')
    output = tmp_path/"result.json"
    result = subprocess.run([sys.executable, "-B",
        str(ROOT/"integrations/ocrv/slk_checker_recovery.py"), operation,
        "--request", str(source), "--output", str(output)],
        capture_output=True, text=True, check=False)
    assert result.returncode == 64
    assert json.loads(result.stdout)["error_code"] == "OUTPUT_REVIEW_RECOVERY_RETIRED"
    assert source.read_bytes() == b'original non-JSON report\r\n'
    assert not output.exists()


@pytest.mark.skipif(os.name != 'nt', reason='public Windows launcher')
def test_public_launcher_exposes_explicit_source_bound_resume():
    result = subprocess.run([str(ROOT / 'integrations/ocrv/slk-checker.cmd'),
        '--slk-resume-review', '--help'], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    assert '--source-attempt' in result.stdout and '--resume-session' in result.stdout
    assert '--invocation-id' in result.stdout and '--binding' in result.stdout
