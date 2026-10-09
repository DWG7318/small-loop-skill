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
