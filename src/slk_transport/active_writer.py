"""One-shot recovery into the exact active Codex Supervisor turn."""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict
from pathlib import Path
from typing import Any, Mapping

from .adapters.codex import CodexAdapter, active_turn_id, resolve_codex_command
from .contracts import ContractError, parse_delivery
from .evidence import Attempt
from .jsonrpc import JsonRpcProcess


def _object(path: Path, label: str) -> Mapping[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContractError(f"active-writer {label} is unreadable") from exc
    if not isinstance(value, dict):
        raise ContractError(f"active-writer {label} must be an object")
    return value


def _recovery_prompt(envelope: Mapping[str, Any], recovery_message_id: str) -> str:
    value = {
        "schema_version": "slk.transport-active-writer-message/v1",
        "recovery_of_message_id": envelope["message_id"],
        "recovery_message_id": recovery_message_id,
        "run_id": envelope["run_id"],
        "go_id": envelope["go_id"],
        "cell_id": envelope["cell_id"],
        "token_sequence": envelope["token_sequence"],
        "payload_type": envelope["payload_type"],
        "payload_sha256": envelope["payload_sha256"],
        "payload": envelope["payload"],
    }
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return (
        "SLK active-writer recovery. This is a new auditable logical message for the exact "
        "already-active Supervisor turn; do not replay the failed transport envelope.\n"
        f"<slk-active-writer-recovery>{encoded}</slk-active-writer-recovery>"
    )


def recover_active_writer(
    attempt_root: Path | str,
    endpoint_raw: Mapping[str, Any],
    envelope_raw: Mapping[str, Any],
) -> dict[str, Any]:
    parsed = parse_delivery(endpoint_raw, envelope_raw)
    endpoint = parsed.endpoint
    envelope = parsed.envelope
    CodexAdapter().validate_address(endpoint)
    if (envelope.sender_role, envelope.receiver_role) != ("checker", "supervisor"):
        raise ContractError("active-writer recovery is limited to exact Checker-to-Supervisor handoffs")

    original = Path(attempt_root).resolve() / envelope.run_id / envelope.message_id
    endpoint_path = original / "endpoint.json"
    envelope_path = original / "envelope.json"
    failed_path = original / "failed.json"
    active_path = original / "active-writer.json"
    if not all(path.is_file() for path in (endpoint_path, envelope_path, failed_path, active_path)):
        raise ContractError("active-writer recovery requires the immutable failed attempt")
    if _object(endpoint_path, "endpoint identity") != asdict(endpoint) or _object(
        envelope_path, "envelope identity"
    ) != asdict(envelope):
        raise ContractError("active-writer recovery changed the original delivery identity")
    failed = _object(failed_path, "failed result")
    if failed.get("error_code") != "CODEX_ACTIVE_WRITER" or (original / "started.json").exists():
        raise ContractError("active-writer recovery requires failure without native start proof")
    active = _object(active_path, "active turn evidence")
    expected_active = {
        "schema_version": "slk.transport-active-writer/v1",
        "message_id": envelope.message_id,
        "run_id": envelope.run_id,
        "thread_id": endpoint.address["thread_id"],
        "active_turn_id": active.get("active_turn_id"),
        "payload_sha256": envelope.payload_sha256,
        "status": "active_writer",
    }
    if active != expected_active or not isinstance(active.get("active_turn_id"), str):
        raise ContractError("active-writer evidence does not match the failed delivery identity")

    recovery_root = original / "recovery" / "active-writer"
    if recovery_root.exists():
        raise ContractError("active-writer recovery already exists")
    recovery_root.mkdir(parents=True, exist_ok=False)
    attempt = Attempt(recovery_root)
    client: JsonRpcProcess | None = None
    recovery_message_id = str(uuid.uuid4())
    thread_id = str(endpoint.address["thread_id"])
    expected_turn_id = str(active["active_turn_id"])
    startup_timeout = float(endpoint.address["startup_timeout_seconds"])
    try:
        command = resolve_codex_command(
            list(endpoint.address["command"]), attempt=attempt, thread_id=thread_id
        )
        client = JsonRpcProcess(command, Path(str(endpoint.address["cwd"])))
        client.request(
            1,
            "initialize",
            {"clientInfo": {"name": "slk_transport", "title": "SLK Transport", "version": "4.4.4"}},
            startup_timeout,
        )
        client.notify("initialized", {})
        read = client.request(
            2,
            "thread/read",
            {"threadId": thread_id, "includeTurns": False},
            startup_timeout,
        )
        thread = read.get("thread")
        request_id = 3

        def list_turns(cursor: str | None) -> Mapping[str, Any]:
            nonlocal request_id
            result = client.request(
                request_id,
                "thread/turns/list",
                {
                    "threadId": thread_id,
                    "cursor": cursor,
                    "limit": 50,
                    "sortDirection": "desc",
                    "itemsView": "summary",
                },
                startup_timeout,
            )
            request_id += 1
            return result

        if not isinstance(thread, Mapping) or active_turn_id(
            thread, list_turns=list_turns
        ) != expected_turn_id:
            raise ContractError("active-writer recovery active turn changed")
        client.request(
            request_id,
            "turn/steer",
            {
                "threadId": thread_id,
                "expectedTurnId": expected_turn_id,
                "input": [
                    {
                        "type": "text",
                        "text": _recovery_prompt(asdict(envelope), recovery_message_id),
                    }
                ],
                "clientUserMessageId": recovery_message_id,
            },
            startup_timeout,
        )
        receipt = {
            "schema_version": "slk.transport-active-writer-recovery/v1",
            "recovery_of_message_id": envelope.message_id,
            "recovery_message_id": recovery_message_id,
            "thread_id": thread_id,
            "expected_turn_id": expected_turn_id,
            "payload_sha256": envelope.payload_sha256,
            "status": "started",
        }
        attempt.write_json_once("recovery.json", receipt)
        attempt.write_json_once(
            "started.json",
            {
                "message_id": recovery_message_id,
                "run_id": envelope.run_id,
                "status": "started",
                "thread_id": thread_id,
                "turn_id": expected_turn_id,
                "recovery_of_message_id": envelope.message_id,
            },
        )
        return receipt
    finally:
        if client is not None:
            client.close()
            attempt.write_text_once("native.stdout.txt", "\n".join(client.transcript) + "\n")
            attempt.write_text_once(
                "native.stderr.txt",
                "\n".join(client.stderr_lines) + ("\n" if client.stderr_lines else ""),
            )
