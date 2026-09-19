from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path

import pytest

from slk_transport.adapters.base import AdapterError
from slk_transport.adapters.ocrv import OcrvAdapter
from slk_transport.contracts import Endpoint, Envelope, canonical_json_sha256
from slk_transport.evidence import AttemptStore

from test_contracts import endpoint_value, envelope_value


FAKE_OCRV = Path(__file__).with_name("fake_ocrv.py")


def checker_endpoint(tmp_path: Path, mode: str = "normal") -> Endpoint:
    runtime_root = tmp_path / "ocrv-runtime"
    runtime_root.mkdir(parents=True, exist_ok=True)
    raw = endpoint_value(role="checker", version=2)
    raw["address"] = {
        "command": [sys.executable, str(FAKE_OCRV), mode],
        "runtime_root": str(runtime_root),
        "timeout_seconds": 5,
    }
    return Endpoint.from_dict(raw)


def candidate_envelope(tmp_path: Path) -> Envelope:
    repository = tmp_path / "repository"
    repository.mkdir(parents=True, exist_ok=True)
    payload = {
        "repository": str(repository),
        "candidate": {"kind": "workspace"},
        "cell_goal": "Verify the transport probe candidate.",
        "d1_criteria": ["The probe nonce remains bound to RUN-A."],
        "evidence_files": [],
    }
    raw = envelope_value(sender_role="worker", receiver_role="checker")
    raw["payload_type"] = "CANDIDATE_READY"
    raw["payload"] = payload
    raw["payload_sha256"] = canonical_json_sha256(payload)
    return Envelope.from_dict(raw)


def test_ocrv_candidate_review_records_run_cell_invocation_and_session(tmp_path: Path) -> None:
    endpoint = checker_endpoint(tmp_path)
    envelope = candidate_envelope(tmp_path)
    attempt = AttemptStore(tmp_path / "attempts").create(envelope)

    result = OcrvAdapter().deliver(endpoint, envelope, attempt)

    assert result.status == "completed"
    assert result.native_identity["run_id"] == "RUN-A"
    assert result.native_identity["cell_id"] == "CELL-001"
    assert result.native_identity["review_invocation_id"]
    assert str(result.native_identity["session_id"]).startswith("ocrv-session-")
    assert result.native_identity["provider"] == "dashscope-tokenplan"
    assert result.native_identity["model"] == "qwen3.8-max"
    assert (attempt.root / "started.json").is_file()
    assert (attempt.root / "ocrv-result.json").is_file()


def test_ocrv_fails_closed_when_session_identity_is_missing(tmp_path: Path) -> None:
    endpoint = checker_endpoint(tmp_path, "missing-session")
    envelope = candidate_envelope(tmp_path)
    attempt = AttemptStore(tmp_path / "attempts").create(envelope)

    with pytest.raises(AdapterError) as error:
        OcrvAdapter().deliver(endpoint, envelope, attempt)

    assert error.value.error_code == "OCRV_RESULT_INVALID"
    assert not (attempt.root / "started.json").exists()


def test_ocrv_preserves_a_valid_incomplete_review_without_calling_it_pass(tmp_path: Path) -> None:
    endpoint = checker_endpoint(tmp_path, "incomplete")
    envelope = candidate_envelope(tmp_path)
    attempt = AttemptStore(tmp_path / "attempts").create(envelope)

    result = OcrvAdapter().deliver(endpoint, envelope, attempt)

    assert result.status == "completed"
    assert result.native_identity["verdict"] == "INCOMPLETE"
    assert result.native_identity["exit_code"] == 3
    assert (attempt.root / "started.json").is_file()


def test_checker_dispatch_creates_exact_worker_delivery_without_running_d1(tmp_path: Path) -> None:
    checker = checker_endpoint(tmp_path)
    worker_raw = endpoint_value(role="worker", version=1)
    worker_raw["agent_runtime"] = "dsh"
    worker_raw["adapter"] = "dsh-worker"
    worker_raw["address"] = {"command": ["D:/DSH/dsh-slk.cmd"]}
    worker = Endpoint.from_dict(worker_raw)
    payload = {
        "worker_endpoint": worker_raw,
        "worker_payload": {"probe_nonce": "A-001", "task": "No project change probe."},
    }
    raw = envelope_value()
    raw["payload_type"] = "CELL_DISPATCH"
    raw["payload"] = payload
    raw["payload_sha256"] = canonical_json_sha256(payload)
    envelope = Envelope.from_dict(raw)
    attempt = AttemptStore(tmp_path / "attempts").create(envelope)

    result = OcrvAdapter().deliver(checker, envelope, attempt)

    assert result.native_identity["checker_operation"] == "dispatch"
    checker_result = json.loads((attempt.root / "checker-result.json").read_text(encoding="utf-8"))
    next_envelope = checker_result["next_envelope"]
    assert checker_result["next_endpoint"]["role_instance_id"] == "RUN-A-worker-001"
    assert next_envelope["sender_role"] == "checker"
    assert next_envelope["receiver_role"] == "worker"
    assert next_envelope["token_sequence"] == 2
    assert next_envelope["run_id"] == "RUN-A"
    assert next_envelope["go_id"] == "GO-001"
    assert next_envelope["cell_id"] == "CELL-001"


def test_ocrv_address_is_closed(tmp_path: Path) -> None:
    endpoint = checker_endpoint(tmp_path)
    invalid = Endpoint(
        **{
            **endpoint.__dict__,
            "address": {**endpoint.address, "conversation_title": "Checker"},
        }
    )

    with pytest.raises(AdapterError) as error:
        OcrvAdapter().validate_address(invalid)

    assert error.value.error_code == "OCRV_ADDRESS_INVALID"
