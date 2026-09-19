from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from slk_transport.adapters.base import AdapterError
from slk_transport.contracts import ContractError, DeliveryResult, Endpoint, Envelope
from slk_transport.dispatcher import dispatch_once
from slk_transport.evidence import Attempt

from test_contracts import endpoint_value, envelope_value


class CompletingAdapter:
    def __init__(self) -> None:
        self.calls = 0

    def validate_address(self, endpoint: Endpoint) -> None:
        assert endpoint.address

    def deliver(self, endpoint: Endpoint, envelope: Envelope, attempt: Attempt) -> DeliveryResult:
        self.calls += 1
        attempt.write_json_once(
            "started.json",
            {
                "message_id": envelope.message_id,
                "run_id": envelope.run_id,
                "status": "started",
            },
        )
        return DeliveryResult(
            schema_version="slk.transport-result/v1",
            message_id=envelope.message_id,
            run_id=envelope.run_id,
            adapter=endpoint.adapter,
            status="completed",
            native_identity={"native_id": "native-001"},
            error_code=None,
            evidence=("started.json",),
        )


class FailingBeforeStartAdapter:
    def validate_address(self, endpoint: Endpoint) -> None:
        return None

    def deliver(self, endpoint: Endpoint, envelope: Envelope, attempt: Attempt) -> DeliveryResult:
        raise AdapterError("NATIVE_START_REJECTED", "native runtime rejected the task")


class UnprovedStartAdapter:
    def validate_address(self, endpoint: Endpoint) -> None:
        return None

    def deliver(self, endpoint: Endpoint, envelope: Envelope, attempt: Attempt) -> DeliveryResult:
        return DeliveryResult(
            schema_version="slk.transport-result/v1",
            message_id=envelope.message_id,
            run_id=envelope.run_id,
            adapter=endpoint.adapter,
            status="completed",
            native_identity={},
            error_code=None,
            evidence=(),
        )


class InvalidAddressAdapter:
    def validate_address(self, endpoint: Endpoint) -> None:
        raise AdapterError("ENDPOINT_ADDRESS_INVALID", "address invalid")

    def deliver(self, endpoint: Endpoint, envelope: Envelope, attempt: Attempt) -> DeliveryResult:
        raise AssertionError("delivery must not run")


def adapter_map(adapter) -> dict[str, object]:
    return {"ocrv-checker": adapter}


def test_completed_delivery_writes_closed_lifecycle(tmp_path: Path) -> None:
    adapter = CompletingAdapter()

    result = dispatch_once(
        endpoint_value(),
        envelope_value(),
        tmp_path,
        adapters=adapter_map(adapter),
    )

    attempt = tmp_path / "RUN-A" / envelope_value()["message_id"]
    assert result.status == "completed"
    assert adapter.calls == 1
    assert sorted(path.name for path in attempt.iterdir()) == [
        "accepted.json",
        "completed.json",
        "endpoint.json",
        "envelope.json",
        "started.json",
    ]


def test_failed_delivery_keeps_the_same_token_boundary(tmp_path: Path) -> None:
    envelope = envelope_value()
    envelope["token_sequence"] = 7

    result = dispatch_once(
        endpoint_value(),
        envelope,
        tmp_path,
        adapters=adapter_map(FailingBeforeStartAdapter()),
    )

    attempt = tmp_path / "RUN-A" / envelope["message_id"]
    assert result.status == "failed"
    assert result.error_code == "NATIVE_START_REJECTED"
    assert not (attempt / "started.json").exists()
    recorded = json.loads((attempt / "envelope.json").read_text(encoding="utf-8"))
    assert recorded["token_sequence"] == 7
    assert recorded["message_id"] == envelope["message_id"]


def test_completed_claim_without_native_start_evidence_fails(tmp_path: Path) -> None:
    result = dispatch_once(
        endpoint_value(),
        envelope_value(),
        tmp_path,
        adapters=adapter_map(UnprovedStartAdapter()),
    )

    assert result.status == "failed"
    assert result.error_code == "NATIVE_START_UNPROVED"
    assert not (tmp_path / "RUN-A" / envelope_value()["message_id"] / "completed.json").exists()


def test_invalid_address_is_rejected_before_attempt_creation(tmp_path: Path) -> None:
    with pytest.raises(AdapterError, match="address invalid"):
        dispatch_once(
            endpoint_value(),
            envelope_value(),
            tmp_path,
            adapters=adapter_map(InvalidAddressAdapter()),
        )

    assert not tmp_path.exists() or not any(tmp_path.rglob("*.json"))


def test_two_runs_cannot_cross_endpoints(tmp_path: Path) -> None:
    endpoint = endpoint_value(run_id="RUN-B")

    with pytest.raises(ContractError, match="run_id"):
        dispatch_once(
            endpoint,
            envelope_value(run_id="RUN-A"),
            tmp_path,
            adapters=adapter_map(CompletingAdapter()),
        )

    assert not tmp_path.exists() or not any(tmp_path.rglob("*.json"))


def test_exact_retry_reuses_terminal_result_without_rerunning_agent(tmp_path: Path) -> None:
    adapter = CompletingAdapter()
    first = dispatch_once(
        endpoint_value(),
        envelope_value(),
        tmp_path,
        adapters=adapter_map(adapter),
    )
    second = dispatch_once(
        endpoint_value(),
        envelope_value(),
        tmp_path,
        adapters=adapter_map(adapter),
    )

    assert first == second
    assert adapter.calls == 1


def test_same_message_id_with_changed_payload_is_rejected(tmp_path: Path) -> None:
    adapter = CompletingAdapter()
    dispatch_once(
        endpoint_value(),
        envelope_value(),
        tmp_path,
        adapters=adapter_map(adapter),
    )
    changed = envelope_value()
    changed["token_sequence"] = 2

    with pytest.raises(ContractError, match="message identity collision"):
        dispatch_once(
            endpoint_value(),
            changed,
            tmp_path,
            adapters=adapter_map(adapter),
        )

    assert adapter.calls == 1
