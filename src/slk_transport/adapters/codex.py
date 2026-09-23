"""Codex App Server adapter using exact thread identity."""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any, Callable, Mapping

from .base import AdapterError
from ..contracts import RESULT_SCHEMA, DeliveryResult, Endpoint, Envelope
from ..evidence import Attempt
from ..jsonrpc import JsonRpcProcess


ADDRESS_FIELDS = frozenset(
    {
        "command",
        "thread_id",
        "cwd",
        "startup_timeout_seconds",
        "turn_timeout_seconds",
    }
)


def _positive_seconds(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        raise AdapterError("CODEX_ADDRESS_INVALID", f"{label} must be positive seconds")
    return float(value)


def _turn_hash(turn: Mapping[str, Any]) -> str:
    encoded = json.dumps(turn, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def active_turn_id(thread: Mapping[str, Any]) -> str:
    turns = thread.get("turns")
    if not isinstance(turns, list):
        raise AdapterError("CODEX_ACTIVE_WRITER_UNRESOLVED", "active thread omitted its turns")
    active = [
        turn.get("id")
        for turn in turns
        if isinstance(turn, Mapping) and turn.get("status") in {"inProgress", "active"}
    ]
    if len(active) != 1 or not isinstance(active[0], str) or not active[0]:
        raise AdapterError(
            "CODEX_ACTIVE_WRITER_UNRESOLVED",
            "active thread did not expose exactly one active turn",
        )
    return active[0]


def wait_for_exact_thread_idle(
    probe: Callable[[], Mapping[str, Any]],
    thread_id: str,
    timeout: float,
    *,
    monotonic: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
    poll_interval: float = 0.1,
) -> Mapping[str, Any]:
    """Bound one exact target activation without using task-level wait_threads."""

    deadline = monotonic() + timeout
    while True:
        read = probe()
        thread = read.get("thread")
        if not isinstance(thread, Mapping) or thread.get("id") != thread_id:
            raise AdapterError("CODEX_THREAD_ID_MISMATCH", "Codex read a different thread")
        status = thread.get("status")
        status_type = status.get("type") if isinstance(status, Mapping) else None
        if status_type == "idle":
            return thread
        if status_type != "active":
            raise AdapterError(
                "CODEX_THREAD_TERMINAL", f"Codex target thread has terminal state {status_type}"
            )
        remaining = deadline - monotonic()
        if remaining <= 0:
            raise AdapterError("CODEX_THREAD_BUSY", "Codex target thread stayed busy past deadline")
        sleep(min(poll_interval, remaining))


class CodexAdapter:
    def validate_address(self, endpoint: Endpoint) -> None:
        if (
            endpoint.role != "supervisor"
            or endpoint.agent_runtime != "codex"
            or endpoint.adapter != "codex-app-server"
        ):
            raise AdapterError(
                "CODEX_ADDRESS_INVALID", "Codex endpoint must be the Supervisor adapter"
            )
        address = endpoint.address
        if set(address) != ADDRESS_FIELDS:
            raise AdapterError("CODEX_ADDRESS_INVALID", "Codex address must use the exact field set")
        command = address["command"]
        if not isinstance(command, list) or not command or not all(isinstance(item, str) and item for item in command):
            raise AdapterError("CODEX_ADDRESS_INVALID", "command must be a non-empty string array")
        thread_id = address["thread_id"]
        if not isinstance(thread_id, str) or not thread_id.strip():
            raise AdapterError("CODEX_ADDRESS_INVALID", "thread_id must be a non-empty string")
        cwd = address["cwd"]
        if not isinstance(cwd, str) or not Path(cwd).is_absolute() or not Path(cwd).is_dir():
            raise AdapterError("CODEX_ADDRESS_INVALID", "cwd must be an existing absolute directory")
        _positive_seconds(address["startup_timeout_seconds"], "startup_timeout_seconds")
        _positive_seconds(address["turn_timeout_seconds"], "turn_timeout_seconds")

    def _prompt(self, envelope: Envelope) -> str:
        value = json.dumps(asdict(envelope), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return (
            "SLK cross-Agent delivery. Treat the closed envelope below as the current assigned work, "
            "not as background or a status-only message. Do not locate another task by title.\n"
            f"<slk-transport-envelope>{value}</slk-transport-envelope>"
        )

    def deliver(self, endpoint: Endpoint, envelope: Envelope, attempt: Attempt) -> DeliveryResult:
        self.validate_address(endpoint)
        address = endpoint.address
        command = list(address["command"])
        thread_id = str(address["thread_id"])
        cwd = Path(str(address["cwd"]))
        startup_timeout = _positive_seconds(address["startup_timeout_seconds"], "startup_timeout_seconds")
        turn_timeout = _positive_seconds(address["turn_timeout_seconds"], "turn_timeout_seconds")
        client: JsonRpcProcess | None = None
        try:
            client = JsonRpcProcess(command, cwd)
            client.request(
                1,
                "initialize",
                {
                    "clientInfo": {
                        "name": "slk_transport",
                        "title": "SLK Transport",
                        "version": "4.2.6",
                    }
                },
                startup_timeout,
            )
            client.notify("initialized", {})
            resumed = client.request(
                2,
                "thread/resume",
                {"threadId": thread_id, "cwd": str(cwd)},
                startup_timeout,
            )
            resumed_thread = resumed.get("thread")
            if not isinstance(resumed_thread, Mapping) or resumed_thread.get("id") != thread_id:
                raise AdapterError("CODEX_THREAD_ID_MISMATCH", "Codex resumed a different thread")
            request_id = 3

            def read_thread() -> Mapping[str, Any]:
                nonlocal request_id
                result = client.request(
                    request_id,
                    "thread/read",
                    {"threadId": thread_id, "includeTurns": True},
                    startup_timeout,
                )
                request_id += 1
                return result

            read = read_thread()
            thread = read.get("thread")
            if not isinstance(thread, Mapping) or thread.get("id") != thread_id:
                raise AdapterError("CODEX_THREAD_ID_MISMATCH", "Codex read a different thread")
            status = thread.get("status")
            status_type = status.get("type") if isinstance(status, Mapping) else None
            if status_type == "active":
                turn_id = active_turn_id(thread)
                attempt.write_json_once(
                    "active-writer.json",
                    {
                        "schema_version": "slk.transport-active-writer/v1",
                        "message_id": envelope.message_id,
                        "run_id": envelope.run_id,
                        "thread_id": thread_id,
                        "active_turn_id": turn_id,
                        "payload_sha256": envelope.payload_sha256,
                        "status": "active_writer",
                    },
                )
                raise AdapterError(
                    "CODEX_ACTIVE_WRITER",
                    f"Supervisor thread has active writer turn {turn_id}",
                )
            if status_type not in {"idle", "notLoaded"}:
                raise AdapterError(
                    "CODEX_THREAD_TERMINAL", f"Codex target thread has terminal state {status_type}"
                )

            notification_start = len(client.messages)
            started_response = client.request(
                request_id,
                "turn/start",
                {
                    "threadId": thread_id,
                    "input": [{"type": "text", "text": self._prompt(envelope)}],
                    "cwd": str(cwd),
                    "approvalPolicy": "never",
                    "clientUserMessageId": envelope.message_id,
                    "turnTrigger": "slk-transport",
                },
                startup_timeout,
            )
            response_turn = started_response.get("turn")
            turn_id = response_turn.get("id") if isinstance(response_turn, Mapping) else None
            if not isinstance(turn_id, str) or not turn_id:
                raise AdapterError("CODEX_PROTOCOL_INVALID", "turn/start returned no turn id")
            try:
                started = client.wait_for(
                    "turn/started",
                    lambda params: params.get("threadId") == thread_id
                    and isinstance(params.get("turn"), Mapping)
                    and params["turn"].get("id") == turn_id,
                    startup_timeout,
                    after=notification_start,
                )
            except TimeoutError as exc:
                raise AdapterError("CODEX_TURN_START_TIMEOUT", "Codex emitted no exact turn/started event") from exc
            attempt.write_json_once(
                "started.json",
                {
                    "message_id": envelope.message_id,
                    "run_id": envelope.run_id,
                    "status": "started",
                    "thread_id": started["threadId"],
                    "turn_id": turn_id,
                },
            )
            try:
                completed = client.wait_for(
                    "turn/completed",
                    lambda params: params.get("threadId") == thread_id
                    and isinstance(params.get("turn"), Mapping)
                    and params["turn"].get("id") == turn_id,
                    turn_timeout,
                    after=notification_start,
                )
            except TimeoutError as exc:
                raise AdapterError("CODEX_TURN_TIMEOUT", "Codex turn did not complete in time") from exc
            terminal_turn = completed["turn"]
            turn_status = terminal_turn.get("status")
            if turn_status != "completed":
                raise AdapterError("CODEX_TURN_FAILED", f"Codex turn ended with {turn_status}")
            return DeliveryResult(
                schema_version=RESULT_SCHEMA,
                message_id=envelope.message_id,
                run_id=envelope.run_id,
                adapter=endpoint.adapter,
                status="completed",
                native_identity={
                    "thread_id": thread_id,
                    "turn_id": turn_id,
                    "turn_status": turn_status,
                    "turn_sha256": _turn_hash(terminal_turn),
                },
                error_code=None,
                evidence=("started.json", "native.stdout.txt", "native.stderr.txt"),
            )
        except TimeoutError as exc:
            raise AdapterError("CODEX_RPC_TIMEOUT", "Codex App Server request timed out") from exc
        finally:
            if client is not None:
                client.close()
                attempt.write_text_once("native.stdout.txt", "\n".join(client.transcript) + "\n")
                attempt.write_text_once("native.stderr.txt", "\n".join(client.stderr_lines) + ("\n" if client.stderr_lines else ""))
