"""Evidence-bound recovery through the Codex Desktop host that owns the writer."""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import uuid
from dataclasses import asdict
from pathlib import Path
from typing import Any, Mapping

from .adapters.codex import CodexAdapter
from .contracts import ContractError, parse_delivery
from .evidence import Attempt


REQUEST_SCHEMA = "slk.transport-desktop-current-turn-request/v1"
HOST_RECEIPT_SCHEMA = "slk.transport-desktop-current-turn-host-receipt/v1"
RECOVERY_SCHEMA = "slk.transport-desktop-current-turn-recovery/v1"

REQUEST_FIELDS = frozenset(
    {
        "schema_version",
        "status",
        "original_message_id",
        "recovery_message_id",
        "run_id",
        "go_id",
        "cell_id",
        "token_sequence",
        "sender_role",
        "sender_role_instance_id",
        "receiver_role",
        "receiver_role_instance_id",
        "receiver_endpoint_version",
        "payload_type",
        "payload_sha256",
        "endpoint_sha256",
        "envelope_sha256",
        "target_thread_id",
        "challenge",
        "prompt",
        "prompt_sha256",
    }
)
HOST_RECEIPT_FIELDS = frozenset(
    {
        "schema_version",
        "request_sha256",
        "host_thread_id",
        "host_turn_id",
        "host_session_id",
        "target_thread_id",
        "before",
        "after",
        "status",
    }
)
BEFORE_FIELDS = frozenset({"thread_status", "turn_id", "turn_status"})
AFTER_FIELDS = frozenset(
    {
        "thread_status",
        "turn_id",
        "turn_status",
        "platform_item_id",
        "item_type",
        "item_name",
        "item_namespace",
        "message_sha256",
    }
)


def _canonical_bytes(value: Mapping[str, Any]) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContractError(f"desktop-current-turn {label} is unreadable") from exc
    if not isinstance(value, dict):
        raise ContractError(f"desktop-current-turn {label} must be an object")
    return value


def _closed(value: Mapping[str, Any], fields: frozenset[str], label: str) -> None:
    if set(value) != fields:
        raise ContractError(f"desktop-current-turn {label} must use the exact field set")


def _text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ContractError(f"desktop-current-turn {label} must be non-empty canonical text")
    return value


def _original(
    attempt_root: Path | str,
    endpoint_raw: Mapping[str, Any],
    envelope_raw: Mapping[str, Any],
) -> tuple[Path, dict[str, Any], dict[str, Any], Path, Path]:
    parsed = parse_delivery(endpoint_raw, envelope_raw)
    endpoint = parsed.endpoint
    envelope = parsed.envelope
    CodexAdapter().validate_address(endpoint)
    if (envelope.sender_role, envelope.receiver_role) != ("checker", "supervisor"):
        raise ContractError(
            "desktop-current-turn recovery is limited to exact Checker-to-Supervisor handoffs"
        )
    original = Path(attempt_root).resolve() / envelope.run_id / envelope.message_id
    endpoint_path = original / "endpoint.json"
    envelope_path = original / "envelope.json"
    failed_path = original / "failed.json"
    if not all(path.is_file() for path in (endpoint_path, envelope_path, failed_path)):
        raise ContractError("desktop-current-turn recovery requires the immutable failed attempt")
    persisted_endpoint = _object(endpoint_path, "endpoint identity")
    persisted_envelope = _object(envelope_path, "envelope identity")
    if persisted_endpoint != asdict(endpoint) or persisted_envelope != asdict(envelope):
        raise ContractError("desktop-current-turn recovery changed the original delivery identity")
    failed = _object(failed_path, "failed result")
    if failed.get("error_code") != "CODEX_ACTIVE_WRITER_UNRESOLVED":
        raise ContractError(
            "desktop-current-turn recovery requires an unresolved Desktop writer failure"
        )
    if (original / "started.json").exists() or (original / "active-writer.json").exists():
        raise ContractError("desktop-current-turn recovery requires no prior native start proof")
    exact_retry = (
        original / "recovery" / "exact-1" / envelope.run_id / envelope.message_id
    )
    retry_endpoint_path = exact_retry / "endpoint.json"
    retry_envelope_path = exact_retry / "envelope.json"
    retry_failed_path = exact_retry / "failed.json"
    if not all(
        path.is_file()
        for path in (retry_endpoint_path, retry_envelope_path, retry_failed_path)
    ):
        raise ContractError(
            "desktop-current-turn recovery requires one exhausted exact retry"
        )
    if (
        _object(retry_endpoint_path, "exact retry endpoint") != asdict(endpoint)
        or _object(retry_envelope_path, "exact retry envelope") != asdict(envelope)
        or _object(retry_failed_path, "exact retry failure").get("error_code")
        != "CODEX_ACTIVE_WRITER_UNRESOLVED"
    ):
        raise ContractError(
            "desktop-current-turn exact retry does not match the unresolved delivery"
        )
    if (
        (exact_retry / "started.json").exists()
        or (exact_retry / "completed.json").exists()
        or (exact_retry / "active-writer.json").exists()
        or (original / "recovery" / "active-writer").exists()
    ):
        raise ContractError("desktop-current-turn recovery conflicts with another proven recovery")
    return original, asdict(endpoint), asdict(envelope), endpoint_path, envelope_path


def _message(request: Mapping[str, Any]) -> str:
    value = {
        "schema_version": "slk.transport-desktop-current-turn-message/v1",
        "challenge": request["challenge"],
        "recovery_of_message_id": request["original_message_id"],
        "recovery_message_id": request["recovery_message_id"],
        "run_id": request["run_id"],
        "go_id": request["go_id"],
        "cell_id": request["cell_id"],
        "token_sequence": request["token_sequence"],
        "sender_role": request["sender_role"],
        "sender_role_instance_id": request["sender_role_instance_id"],
        "receiver_role": request["receiver_role"],
        "receiver_role_instance_id": request["receiver_role_instance_id"],
        "receiver_endpoint_version": request["receiver_endpoint_version"],
        "payload_type": request["payload_type"],
        "payload_sha256": request["payload_sha256"],
    }
    encoded = _canonical_bytes(value).decode("utf-8")
    return (
        "SLK Desktop current-turn recovery. Treat this as one new auditable delivery bound "
        "to the preserved failed Checker message; do not replay or rewrite the original.\n"
        f"<slk-desktop-current-turn-recovery>{encoded}</slk-desktop-current-turn-recovery>"
    )


def _validate_request(
    request: Mapping[str, Any],
    endpoint: Mapping[str, Any],
    envelope: Mapping[str, Any],
    endpoint_path: Path,
    envelope_path: Path,
) -> None:
    _closed(request, REQUEST_FIELDS, "request")
    expected = {
        "schema_version": REQUEST_SCHEMA,
        "status": "PREPARED",
        "original_message_id": envelope["message_id"],
        "run_id": envelope["run_id"],
        "go_id": envelope["go_id"],
        "cell_id": envelope["cell_id"],
        "token_sequence": envelope["token_sequence"],
        "sender_role": envelope["sender_role"],
        "sender_role_instance_id": envelope["sender_role_instance_id"],
        "receiver_role": envelope["receiver_role"],
        "receiver_role_instance_id": envelope["receiver_role_instance_id"],
        "receiver_endpoint_version": envelope["receiver_endpoint_version"],
        "payload_type": envelope["payload_type"],
        "payload_sha256": envelope["payload_sha256"],
        "endpoint_sha256": _sha256(endpoint_path.read_bytes()),
        "envelope_sha256": _sha256(envelope_path.read_bytes()),
        "target_thread_id": endpoint["address"]["thread_id"],
    }
    for key, value in expected.items():
        if request.get(key) != value:
            raise ContractError(f"desktop-current-turn request {key} changed delivery identity")
    _text(request.get("recovery_message_id"), "recovery_message_id")
    _text(request.get("challenge"), "challenge")
    prompt = _text(request.get("prompt"), "prompt")
    if prompt != _message(request) or request.get("prompt_sha256") != _sha256(
        prompt.encode("utf-8")
    ):
        raise ContractError("desktop-current-turn request prompt identity is invalid")


def prepare_desktop_current_turn(
    attempt_root: Path | str,
    endpoint_raw: Mapping[str, Any],
    envelope_raw: Mapping[str, Any],
) -> dict[str, Any]:
    original, endpoint, envelope, endpoint_path, envelope_path = _original(
        attempt_root, endpoint_raw, envelope_raw
    )
    recovery_root = original / "recovery" / "desktop-current-turn"
    request_path = recovery_root / "request.json"
    if request_path.is_file():
        request = _object(request_path, "request")
        _validate_request(request, endpoint, envelope, endpoint_path, envelope_path)
        return request
    if recovery_root.exists() and any(recovery_root.iterdir()):
        raise ContractError("desktop-current-turn recovery evidence is incomplete")
    recovery_root.mkdir(parents=True, exist_ok=True)
    request: dict[str, Any] = {
        "schema_version": REQUEST_SCHEMA,
        "status": "PREPARED",
        "original_message_id": envelope["message_id"],
        "recovery_message_id": str(uuid.uuid4()),
        "run_id": envelope["run_id"],
        "go_id": envelope["go_id"],
        "cell_id": envelope["cell_id"],
        "token_sequence": envelope["token_sequence"],
        "sender_role": envelope["sender_role"],
        "sender_role_instance_id": envelope["sender_role_instance_id"],
        "receiver_role": envelope["receiver_role"],
        "receiver_role_instance_id": envelope["receiver_role_instance_id"],
        "receiver_endpoint_version": envelope["receiver_endpoint_version"],
        "payload_type": envelope["payload_type"],
        "payload_sha256": envelope["payload_sha256"],
        "endpoint_sha256": _sha256(endpoint_path.read_bytes()),
        "envelope_sha256": _sha256(envelope_path.read_bytes()),
        "target_thread_id": endpoint["address"]["thread_id"],
        "challenge": secrets.token_hex(32),
        "prompt": "pending",
        "prompt_sha256": "pending",
    }
    request["prompt"] = _message(request)
    request["prompt_sha256"] = _sha256(str(request["prompt"]).encode("utf-8"))
    _validate_request(request, endpoint, envelope, endpoint_path, envelope_path)
    Attempt(recovery_root).write_json_once("request.json", request)
    return request


def _validate_host_receipt(
    receipt: Mapping[str, Any],
    request: Mapping[str, Any],
    environment: Mapping[str, str],
) -> None:
    _closed(receipt, HOST_RECEIPT_FIELDS, "host receipt")
    if receipt.get("schema_version") != HOST_RECEIPT_SCHEMA:
        raise ContractError("desktop-current-turn host receipt schema is invalid")
    if receipt.get("request_sha256") != _sha256(_canonical_bytes(request)):
        raise ContractError("desktop-current-turn host receipt request hash is invalid")
    host_thread_id = _text(receipt.get("host_thread_id"), "host_thread_id")
    host_session_id = _text(receipt.get("host_session_id"), "host_session_id")
    _text(receipt.get("host_turn_id"), "host_turn_id")
    if (
        environment.get("CODEX_INTERNAL_ORIGINATOR_OVERRIDE") != "Codex Desktop"
        or environment.get("CODEX_THREAD_ID") != host_thread_id
        or environment.get("CODEX_SESSION_ID") != host_session_id
    ):
        raise ContractError("desktop-current-turn completion requires the exact Codex Desktop host")
    if receipt.get("target_thread_id") != request["target_thread_id"]:
        raise ContractError("desktop-current-turn target thread does not match the endpoint")
    before = receipt.get("before")
    after = receipt.get("after")
    if not isinstance(before, Mapping) or not isinstance(after, Mapping):
        raise ContractError("desktop-current-turn before/after observations are required")
    _closed(before, BEFORE_FIELDS, "before observation")
    _closed(after, AFTER_FIELDS, "after observation")
    before_turn = _text(before.get("turn_id"), "before turn")
    after_turn = _text(after.get("turn_id"), "after turn")
    if before_turn != after_turn:
        raise ContractError("desktop-current-turn target turn changed during injection")
    if (
        before.get("thread_status") != "active"
        or after.get("thread_status") != "active"
        or before.get("turn_status") not in {"inProgress", "active"}
        or after.get("turn_status") not in {"inProgress", "active"}
    ):
        raise ContractError("desktop-current-turn target turn is not active")
    _text(after.get("platform_item_id"), "platform_item_id")
    if (
        after.get("item_type") != "functionCallOutput"
        or after.get("item_name") != "send_message_to_thread"
        or after.get("item_namespace") != "codex_app"
    ):
        raise ContractError("desktop-current-turn platform injection item is invalid")
    if after.get("message_sha256") != request["prompt_sha256"]:
        raise ContractError("desktop-current-turn injected message hash is invalid")
    if receipt.get("status") != "PLATFORM_READBACK_CONFIRMED":
        raise ContractError("desktop-current-turn platform readback is not confirmed")


def _write_or_match(attempt: Attempt, name: str, value: Mapping[str, Any]) -> None:
    path = attempt.root / name
    if path.is_file():
        if _object(path, name) != dict(value):
            raise ContractError(f"desktop-current-turn {name} conflicts with existing evidence")
        return
    attempt.write_json_once(name, value)


def complete_desktop_current_turn(
    attempt_root: Path | str,
    endpoint_raw: Mapping[str, Any],
    envelope_raw: Mapping[str, Any],
    host_receipt_raw: Mapping[str, Any],
    *,
    environment: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    original, endpoint, envelope, endpoint_path, envelope_path = _original(
        attempt_root, endpoint_raw, envelope_raw
    )
    recovery_root = original / "recovery" / "desktop-current-turn"
    request_path = recovery_root / "request.json"
    if not request_path.is_file():
        raise ContractError("desktop-current-turn recovery must be prepared first")
    request = _object(request_path, "request")
    _validate_request(request, endpoint, envelope, endpoint_path, envelope_path)
    receipt = dict(host_receipt_raw)
    _validate_host_receipt(receipt, request, os.environ if environment is None else environment)
    after = receipt["after"]
    recovery = {
        "schema_version": RECOVERY_SCHEMA,
        "recovery_of_message_id": envelope["message_id"],
        "recovery_message_id": request["recovery_message_id"],
        "run_id": envelope["run_id"],
        "thread_id": request["target_thread_id"],
        "turn_id": after["turn_id"],
        "platform_item_id": after["platform_item_id"],
        "payload_sha256": envelope["payload_sha256"],
        "endpoint_sha256": request["endpoint_sha256"],
        "envelope_sha256": request["envelope_sha256"],
        "status": "started",
    }
    started = {
        "message_id": request["recovery_message_id"],
        "run_id": envelope["run_id"],
        "status": "started",
        "thread_id": request["target_thread_id"],
        "turn_id": after["turn_id"],
        "platform_item_id": after["platform_item_id"],
        "recovery_of_message_id": envelope["message_id"],
    }
    attempt = Attempt(recovery_root)
    _write_or_match(attempt, "host-receipt.json", receipt)
    _write_or_match(attempt, "recovery.json", recovery)
    _write_or_match(attempt, "started.json", started)
    return recovery
