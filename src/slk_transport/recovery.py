"""One-shot inspection and exact replay for an existing SLK delivery."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any, Callable, Mapping

from .adapters.base import Adapter
from .contracts import ContractError, DeliveryResult, parse_delivery
from .dispatcher import dispatch_once


Dispatch = Callable[..., DeliveryResult]


def _read_object(path: Path, label: str) -> Mapping[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContractError(f"exact retry {label} is unreadable") from exc
    if not isinstance(value, dict):
        raise ContractError(f"exact retry {label} must be a JSON object")
    return value


def _attempt_path(
    attempt_root: Path | str, envelope: Mapping[str, Any]
) -> Path:
    run_id = envelope.get("run_id")
    message_id = envelope.get("message_id")
    if not isinstance(run_id, str) or not isinstance(message_id, str):
        raise ContractError("exact retry identity is incomplete")
    return Path(attempt_root).resolve() / run_id / message_id


def _exact_original(
    attempt_root: Path | str,
    endpoint_raw: Mapping[str, Any],
    envelope_raw: Mapping[str, Any],
) -> tuple[Path, dict[str, Any], dict[str, Any]]:
    try:
        parsed = parse_delivery(endpoint_raw, envelope_raw)
    except ContractError as exc:
        raise ContractError(f"exact retry request is invalid: {exc}") from exc
    endpoint = asdict(parsed.endpoint)
    envelope = asdict(parsed.envelope)
    attempt = _attempt_path(attempt_root, envelope)
    endpoint_path = attempt / "endpoint.json"
    envelope_path = attempt / "envelope.json"
    if not endpoint_path.is_file() or not envelope_path.is_file():
        raise ContractError("exact retry requires the immutable original delivery identity")
    persisted_endpoint = dict(_read_object(endpoint_path, "endpoint"))
    persisted_envelope = dict(_read_object(envelope_path, "envelope"))
    parse_delivery(persisted_endpoint, persisted_envelope)
    if persisted_endpoint != endpoint or persisted_envelope != envelope:
        raise ContractError("exact retry changed the original delivery identity")
    return attempt, endpoint, envelope


def _terminal(attempt: Path) -> tuple[str | None, Mapping[str, Any] | None]:
    completed = attempt / "completed.json"
    failed = attempt / "failed.json"
    if completed.is_file() and failed.is_file():
        raise ContractError("exact retry evidence has conflicting terminal results")
    if completed.is_file():
        return "completed", _read_object(completed, "completed result")
    if failed.is_file():
        return "failed", _read_object(failed, "failed result")
    return None, None


def inspect_delivery(
    attempt_root: Path | str,
    endpoint_raw: Mapping[str, Any],
    envelope_raw: Mapping[str, Any],
) -> dict[str, Any]:
    """Inspect one immutable delivery without polling or inferring liveness."""

    attempt, _endpoint, envelope = _exact_original(
        attempt_root, endpoint_raw, envelope_raw
    )
    terminal, _result = _terminal(attempt)
    if (attempt / "started.json").is_file():
        return {
            "status": "ALREADY_STARTED",
            "should_retry": False,
            "run_id": envelope["run_id"],
            "message_id": envelope["message_id"],
        }
    if terminal == "completed":
        return {
            "status": "SUPERVISOR_DECISION_REQUIRED",
            "reason": "COMPLETION_WITHOUT_START_PROOF",
            "should_retry": False,
            "run_id": envelope["run_id"],
            "message_id": envelope["message_id"],
        }
    return {
        "status": "DELIVERY_UNCONFIRMED",
        "reason": "FAILED_OR_NO_NATIVE_START_PROOF" if terminal == "failed" else "NO_NATIVE_START_PROOF",
        "should_retry": True,
        "run_id": envelope["run_id"],
        "message_id": envelope["message_id"],
    }


def retry_exact(
    attempt_root: Path | str,
    endpoint_raw: Mapping[str, Any],
    envelope_raw: Mapping[str, Any],
    *,
    adapters: Mapping[str, Adapter],
    dispatch: Dispatch = dispatch_once,
) -> dict[str, Any]:
    """Replay one persisted delivery exactly once, then stop with a closed result."""

    attempt, endpoint, envelope = _exact_original(
        attempt_root, endpoint_raw, envelope_raw
    )
    inspection = inspect_delivery(attempt_root, endpoint, envelope)
    if inspection["status"] == "ALREADY_STARTED":
        return inspection
    if not inspection["should_retry"]:
        return inspection

    retry_root = attempt / "recovery" / "exact-1"
    retry_attempt = retry_root / str(envelope["run_id"]) / str(envelope["message_id"])
    if retry_attempt.exists():
        terminal, raw_result = _terminal(retry_attempt)
        if (retry_attempt / "started.json").is_file():
            return {
                "status": "RETRY_COMPLETED",
                "run_id": envelope["run_id"],
                "message_id": envelope["message_id"],
            }
        if terminal == "completed":
            return {
                "status": "SUPERVISOR_DECISION_REQUIRED",
                "reason": "EXACT_RETRY_START_UNPROVED",
                "run_id": envelope["run_id"],
                "message_id": envelope["message_id"],
                "result": dict(raw_result or {}),
            }
        if terminal == "failed":
            return {
                "status": "SUPERVISOR_DECISION_REQUIRED",
                "reason": "EXACT_RETRY_EXHAUSTED",
                "run_id": envelope["run_id"],
                "message_id": envelope["message_id"],
                "result": dict(raw_result or {}),
            }
        return {
            "status": "SUPERVISOR_DECISION_REQUIRED",
            "reason": "EXACT_RETRY_EVIDENCE_INCOMPLETE",
            "run_id": envelope["run_id"],
            "message_id": envelope["message_id"],
        }

    result = dispatch(endpoint, envelope, retry_root, adapters=adapters)
    if result.status == "completed" and (retry_attempt / "started.json").is_file():
        return {
            "status": "RETRY_COMPLETED",
            "run_id": envelope["run_id"],
            "message_id": envelope["message_id"],
            "result": result.to_dict(),
        }
    if result.status == "completed":
        return {
            "status": "SUPERVISOR_DECISION_REQUIRED",
            "reason": "EXACT_RETRY_START_UNPROVED",
            "run_id": envelope["run_id"],
            "message_id": envelope["message_id"],
            "result": result.to_dict(),
        }
    return {
        "status": "SUPERVISOR_DECISION_REQUIRED",
        "reason": "EXACT_RETRY_EXHAUSTED",
        "run_id": envelope["run_id"],
        "message_id": envelope["message_id"],
        "result": result.to_dict(),
    }
