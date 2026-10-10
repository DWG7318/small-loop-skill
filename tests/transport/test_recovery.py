from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Mapping

import pytest

from slk_transport.contracts import ContractError, DeliveryResult, RESULT_SCHEMA
from slk_transport.recovery import inspect_delivery, retry_exact
from slk_transport.native_activity import make_native_start

from test_contracts import endpoint_value, envelope_value, payload_hash


def write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")


def delivery() -> tuple[dict[str, Any], dict[str, Any]]:
    endpoint = endpoint_value(role="checker", version=2)
    envelope = envelope_value(
        sender_role="supervisor",
        receiver_role="checker",
        receiver_endpoint_version=2,
    )
    return endpoint, envelope


def seed_identity(root: Path) -> tuple[dict[str, Any], dict[str, Any], Path]:
    endpoint, envelope = delivery()
    attempt = root / str(envelope["run_id"]) / str(envelope["message_id"])
    write_json(attempt / "endpoint.json", endpoint)
    write_json(attempt / "envelope.json", envelope)
    write_json(
        attempt / "accepted.json",
        {
            "message_id": envelope["message_id"],
            "run_id": envelope["run_id"],
            "status": "accepted",
        },
    )
    return endpoint, envelope, attempt


def completed(envelope: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": RESULT_SCHEMA,
        "message_id": envelope["message_id"],
        "run_id": envelope["run_id"],
        "adapter": "ocrv-checker",
        "status": "completed",
        "native_identity": {"session_id": "checker-a"},
        "error_code": None,
        "evidence": ["started.json"],
    }


def failed(envelope: Mapping[str, Any]) -> dict[str, Any]:
    return {
        **completed(envelope),
        "status": "failed",
        "native_identity": {},
        "error_code": "DELIVERY_UNCONFIRMED",
    }


def start_proof(endpoint, envelope):
    return make_native_start(adapter=endpoint["adapter"], run_id=envelope["run_id"],
        cell_id=envelope["cell_id"], message_id=envelope["message_id"],
        request_sha256=envelope["payload_sha256"], native_request_sha256="a" * 64,
        native_task_kind="ocrv-review", native_task_id="checker-a", native_task_status="RUNNING", pid=os.getpid())


@pytest.mark.parametrize("changed", [None, "endpoint", "envelope", "start"])
def test_inspection_resolves_only_the_exact_retry_without_rewriting_original(tmp_path, changed):
    endpoint, envelope, attempt = seed_identity(tmp_path)
    write_json(attempt / "failed.json", failed(envelope))
    original = {path.name: path.read_bytes() for path in attempt.iterdir() if path.is_file()}
    retry = attempt / "recovery" / "exact-1" / envelope["run_id"] / envelope["message_id"]
    write_json(retry / "endpoint.json", {**endpoint, **({"endpoint_version": 999} if changed == "endpoint" else {})})
    write_json(retry / "envelope.json", {**envelope, **({"token_sequence": 999} if changed == "envelope" else {})})
    write_json(retry / "started.json", {**start_proof(endpoint, envelope),
        **({"request_sha256": "f" * 64} if changed == "start" else {})})
    if changed:
        with pytest.raises(ValueError):
            inspect_delivery(tmp_path, endpoint, envelope)
    else:
        result = inspect_delivery(tmp_path, endpoint, envelope)
        assert result["status"] == "ALREADY_STARTED" and not result["should_retry"]
        assert result["native_start"]["message_id"] == envelope["message_id"]
        assert result["native_start_path"] == str(retry / "started.json")
    assert not (attempt / "started.json").exists()
    assert {path.name: path.read_bytes() for path in attempt.iterdir() if path.is_file()} == original


def test_inspect_stops_when_original_delivery_has_native_start_proof(tmp_path: Path) -> None:
    endpoint, envelope, attempt = seed_identity(tmp_path)
    write_json(attempt / "started.json", start_proof(endpoint, envelope))
    write_json(attempt / "completed.json", completed(envelope))

    result = inspect_delivery(tmp_path, endpoint, envelope)

    assert result["status"] == "ALREADY_STARTED"
    assert result["should_retry"] is False


def test_inspect_reports_unconfirmed_without_claiming_work(tmp_path: Path) -> None:
    endpoint, envelope, _attempt = seed_identity(tmp_path)

    result = inspect_delivery(tmp_path, endpoint, envelope)

    assert result["status"] == "DELIVERY_UNCONFIRMED"
    assert result["should_retry"] is True


@pytest.mark.parametrize(
    "mutate",
    [
        lambda endpoint, envelope: envelope.update(message_id="10000000-0000-4000-8000-000000000001"),
        lambda endpoint, envelope: endpoint.update(endpoint_version=3),
        lambda endpoint, envelope: envelope.update(go_id="GO-OTHER"),
        lambda endpoint, envelope: envelope.update(cell_id="CELL-OTHER"),
        lambda endpoint, envelope: envelope.update(token_sequence=2),
        lambda endpoint, envelope: envelope.update(
            payload={"changed": True}, payload_sha256=payload_hash({"changed": True})
        ),
    ],
)
def test_retry_rejects_any_change_to_the_original_delivery_identity(
    tmp_path: Path, mutate
) -> None:
    endpoint, envelope, attempt = seed_identity(tmp_path)
    write_json(attempt / "failed.json", failed(envelope))
    mutate(endpoint, envelope)

    with pytest.raises(ContractError, match="exact retry"):
        retry_exact(tmp_path, endpoint, envelope, adapters={})


def test_retry_dispatches_the_exact_original_once(tmp_path: Path) -> None:
    endpoint, envelope, attempt = seed_identity(tmp_path)
    write_json(attempt / "failed.json", failed(envelope))
    calls: list[tuple[Mapping[str, Any], Mapping[str, Any], Path]] = []

    def dispatch(endpoint_raw, envelope_raw, attempt_root, *, adapters):
        retry_root = Path(attempt_root)
        calls.append((endpoint_raw, envelope_raw, retry_root))
        retry_attempt = retry_root / str(envelope_raw["run_id"]) / str(
            envelope_raw["message_id"]
        )
        write_json(retry_attempt / "endpoint.json", endpoint_raw)
        write_json(retry_attempt / "envelope.json", envelope_raw)
        write_json(retry_attempt / "started.json", start_proof(endpoint_raw, envelope_raw))
        write_json(retry_attempt / "completed.json", completed(envelope_raw))
        return DeliveryResult.from_dict(completed(envelope_raw))

    result = retry_exact(
        tmp_path,
        endpoint,
        envelope,
        adapters={},
        dispatch=dispatch,
    )

    assert result["status"] == "RETRY_COMPLETED"
    assert calls[0][0] == endpoint
    assert calls[0][1] == envelope
    assert calls[0][2] == attempt / "recovery" / "exact-1"


def test_retry_cannot_claim_success_without_native_start_proof(tmp_path: Path) -> None:
    endpoint, envelope, attempt = seed_identity(tmp_path)
    write_json(attempt / "failed.json", failed(envelope))

    def dispatch(endpoint_raw, envelope_raw, attempt_root, *, adapters):
        return DeliveryResult.from_dict(completed(envelope_raw))

    result = retry_exact(
        tmp_path,
        endpoint,
        envelope,
        adapters={},
        dispatch=dispatch,
    )

    assert result["status"] == "SUPERVISOR_DECISION_REQUIRED"
    assert result["reason"] == "EXACT_RETRY_START_UNPROVED"


def test_persisted_retry_completion_without_start_proof_is_rejected(tmp_path: Path) -> None:
    endpoint, envelope, attempt = seed_identity(tmp_path)
    write_json(attempt / "failed.json", failed(envelope))
    retry_attempt = attempt / "recovery" / "exact-1" / str(envelope["run_id"]) / str(
        envelope["message_id"]
    )
    write_json(retry_attempt / "endpoint.json", endpoint)
    write_json(retry_attempt / "envelope.json", envelope)
    write_json(retry_attempt / "completed.json", completed(envelope))

    result = retry_exact(tmp_path, endpoint, envelope, adapters={})

    assert result["status"] == "SUPERVISOR_DECISION_REQUIRED"
    assert result["reason"] == "EXACT_RETRY_START_UNPROVED"


def test_retry_is_not_attempted_when_native_start_is_already_proven(tmp_path: Path) -> None:
    endpoint, envelope, attempt = seed_identity(tmp_path)
    write_json(attempt / "started.json", start_proof(endpoint, envelope))
    called = False

    def dispatch(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("dispatch must not run")

    result = retry_exact(tmp_path, endpoint, envelope, adapters={}, dispatch=dispatch)

    assert result["status"] == "ALREADY_STARTED"
    assert called is False


def test_failed_exact_retry_is_exhausted_and_never_becomes_a_loop(tmp_path: Path) -> None:
    endpoint, envelope, attempt = seed_identity(tmp_path)
    write_json(attempt / "failed.json", failed(envelope))
    retry_attempt = attempt / "recovery" / "exact-1" / str(envelope["run_id"]) / str(
        envelope["message_id"]
    )
    write_json(retry_attempt / "endpoint.json", endpoint)
    write_json(retry_attempt / "envelope.json", envelope)
    write_json(retry_attempt / "failed.json", failed(envelope))

    result = retry_exact(tmp_path, endpoint, envelope, adapters={})

    assert result["status"] == "SUPERVISOR_DECISION_REQUIRED"
    assert result["reason"] == "EXACT_RETRY_EXHAUSTED"
