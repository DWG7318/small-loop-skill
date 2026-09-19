"""Validate and execute one exact SLK Agent delivery."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any, Mapping

from .adapters.base import Adapter, AdapterError
from .contracts import (
    RESULT_SCHEMA,
    ContractError,
    DeliveryResult,
    Endpoint,
    Envelope,
    parse_delivery,
)
from .evidence import Attempt, AttemptStore


def _plain(value: Endpoint | Envelope) -> dict[str, Any]:
    return asdict(value)


def _read_json(path: Path) -> Mapping[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContractError(f"transport evidence is unreadable: {path.name}") from exc
    if not isinstance(value, dict):
        raise ContractError(f"transport evidence is not an object: {path.name}")
    return value


def _same_identity(path: Path, expected: Mapping[str, Any]) -> None:
    if _read_json(path) != expected:
        raise ContractError("message identity collision with existing transport evidence")


def _existing_result(attempt: Attempt) -> DeliveryResult | None:
    completed = attempt.root / "completed.json"
    failed = attempt.root / "failed.json"
    if completed.is_file() and failed.is_file():
        raise ContractError("transport attempt has conflicting terminal evidence")
    if completed.is_file():
        return DeliveryResult.from_dict(_read_json(completed))
    if failed.is_file():
        return DeliveryResult.from_dict(_read_json(failed))
    return None


def _failure(
    endpoint: Endpoint,
    envelope: Envelope,
    error_code: str,
    attempt: Attempt,
) -> DeliveryResult:
    evidence = tuple(sorted(path.name for path in attempt.root.iterdir() if path.is_file()))
    return DeliveryResult(
        schema_version=RESULT_SCHEMA,
        message_id=envelope.message_id,
        run_id=envelope.run_id,
        adapter=endpoint.adapter,
        status="failed",
        native_identity={},
        error_code=error_code,
        evidence=evidence,
    )


def _validate_result(result: DeliveryResult, endpoint: Endpoint, envelope: Envelope) -> None:
    if result.message_id != envelope.message_id:
        raise ContractError("adapter result message_id mismatch")
    if result.run_id != envelope.run_id:
        raise ContractError("adapter result run_id mismatch")
    if result.adapter != endpoint.adapter:
        raise ContractError("adapter result adapter mismatch")
    if result.status not in {"completed", "failed"}:
        raise ContractError("adapter result must be terminal")


def dispatch_once(
    endpoint_raw: Mapping[str, Any],
    envelope_raw: Mapping[str, Any],
    attempt_root: Path | str,
    *,
    adapters: Mapping[str, Adapter],
) -> DeliveryResult:
    """Deliver one envelope, or return the immutable result of an exact retry."""

    parsed = parse_delivery(endpoint_raw, envelope_raw)
    endpoint = parsed.endpoint
    envelope = parsed.envelope
    try:
        adapter = adapters[endpoint.adapter]
    except KeyError as exc:
        raise AdapterError("ADAPTER_UNAVAILABLE", f"adapter is unavailable: {endpoint.adapter}") from exc
    adapter.validate_address(endpoint)

    attempt = AttemptStore(attempt_root).create(envelope)
    endpoint_path = attempt.root / "endpoint.json"
    envelope_path = attempt.root / "envelope.json"
    endpoint_value = _plain(endpoint)
    envelope_value = _plain(envelope)

    if endpoint_path.exists() or envelope_path.exists():
        if not endpoint_path.is_file() or not envelope_path.is_file():
            raise ContractError("transport attempt has incomplete identity evidence")
        _same_identity(endpoint_path, endpoint_value)
        _same_identity(envelope_path, envelope_value)
        existing = _existing_result(attempt)
        if existing is not None:
            return existing
        raise ContractError("transport attempt exists without terminal evidence")

    attempt.write_json_once("endpoint.json", endpoint_value)
    attempt.write_json_once("envelope.json", envelope_value)
    attempt.write_json_once(
        "accepted.json",
        {
            "message_id": envelope.message_id,
            "run_id": envelope.run_id,
            "status": "accepted",
        },
    )

    try:
        result = adapter.deliver(endpoint, envelope, attempt)
        _validate_result(result, endpoint, envelope)
    except AdapterError as exc:
        result = _failure(endpoint, envelope, exc.error_code, attempt)

    if result.status == "completed" and not (attempt.root / "started.json").is_file():
        result = _failure(endpoint, envelope, "NATIVE_START_UNPROVED", attempt)

    terminal_name = "completed.json" if result.status == "completed" else "failed.json"
    attempt.write_json_once(terminal_name, result.to_dict())
    return result
