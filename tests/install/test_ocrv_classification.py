"""Severity, coverage and process exit are preserved, never converted to D1."""
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

@pytest.mark.parametrize("severity", ["LOW", "MEDIUM", "HIGH", "BLOCKER", "CRITICAL", "MYSTERY"])
@pytest.mark.parametrize("exit_code", [0, 2, 3, 42])
def test_raw_review_never_synthesizes_a_checker_decision(tmp_path, severity, exit_code):
    from slk_transport.adapters.ocrv import OcrvAdapter
    from slk_transport.contracts import ENVELOPE_SCHEMA, Envelope, canonical_json_sha256
    envelope = Envelope.from_dict({
        "schema_version": ENVELOPE_SCHEMA,
        "message_id": "11111111-1111-4111-8111-111111111111", "token_sequence": 1,
        "run_id": "RUN-CLASSIFICATION", "go_id": "GO-A", "cell_id": "CELL-001",
        "sender_role": "worker", "sender_role_instance_id": "WORKER-A",
        "receiver_role": "checker", "receiver_role_instance_id": "CHECKER-A",
        "receiver_endpoint_version": 1, "payload_type": "CANDIDATE_READY",
        "payload": {}, "payload_sha256": canonical_json_sha256({}),
    })
    path = tmp_path / "native-report.json"
    raw = {"comments": [{"severity": severity, "message": "original finding"}],
           "manifest": {"coverage": {"completed": [], "failed": ["criterion"]}}}
    original = json.dumps(raw).encode()
    path.write_bytes(original)
    result = OcrvAdapter().validate_existing_result(path, tmp_path/"request.json",
                                                   envelope, exit_code)
    assert result == raw and path.read_bytes() == original
    assert "verdict" not in result

def test_native_wrapper_has_no_engineering_classifier():
    spec = importlib.util.spec_from_file_location("slk_no_classifier",
        ROOT / "integrations/ocrv/slk_checker_adapter.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert not hasattr(module, "_classify")


def test_retry_metadata_retains_four_429_and_timeout_only_without_private_payloads():
    spec = importlib.util.spec_from_file_location('slk_retry_projection',
        ROOT / 'integrations/ocrv/slk_checker_adapter.py')
    adapter = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(adapter)
    attempts = [{'attempt': 1, 'outcome': 'error', 'error_class': 'rate_limited',
        'failure_phase': 'http', 'status_code': 429, 'retry_after_ms': 275546000 + i * 300000,
        'duration_to_headers_ms': 244 + i * 14, 'reasoning': 'PRIVATE'} for i in range(4)]
    attempts.append({'attempt': 1, 'outcome': 'error', 'error_class': 'timeout',
        'failure_phase': 'context', 'duration_to_headers_ms': 300000})
    report = {'schema_version': 'ocr.llm-retry-report/v1', 'total_requests': 56,
        'failed_requests': 5, 'retried_requests': 0, 'total_retries': 0,
        'recovered_requests': 0, 'cancelled_requests': 0,
        'requests': [{'logical_request_id': str(i), 'provider': 'dashscope-tokenplan',
            'model': 'qwen3.8-max', 'file_path': 'fixture.py', 'task_type': 'main_task',
            'request_no': i + 1, 'outcome': 'failed', 'attempts': [attempt],
            'body': 'PRIVATE'} for i, attempt in enumerate(attempts)], 'credentials': 'PRIVATE'}
    projected = adapter._normalized_retry_report({'retry_report': report})
    assert projected['total_requests'] == 56 and projected['total_retries'] == 0
    assert [r['attempts'][0].get('status_code') for r in projected['requests']] == [429, 429, 429, 429, None]
    assert projected['requests'][0]['attempts'][0]['retry_after_ms'] == 275546000
    assert 'PRIVATE' not in json.dumps(projected)
    assert adapter._normalized_retry_report({}) is None


@pytest.mark.parametrize('requests', [None, {}, [{'attempts': None}], [{'attempts': {}}]])
def test_unavailable_retry_metadata_is_unknown_not_empty_or_a_report_failure(requests):
    spec = importlib.util.spec_from_file_location('slk_retry_bad_projection',
        ROOT / 'integrations/ocrv/slk_checker_adapter.py')
    adapter = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(adapter)
    assert adapter._normalized_retry_report({'retry_report': {
        'schema_version': 'ocr.llm-retry-report/v1', 'requests': requests}}) is None
