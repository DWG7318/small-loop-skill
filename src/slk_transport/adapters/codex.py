"""Codex App Server adapter using exact thread identity."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any, Callable, Mapping

from .base import AdapterError
from ..contracts import RESULT_SCHEMA, DeliveryResult, Endpoint, Envelope
from ..evidence import Attempt
from ..jsonrpc import JsonRpcProcess
from ..native_activity import make_native_start


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


def active_turn_id(
    thread: Mapping[str, Any],
    *,
    list_turns: Callable[[str | None], Mapping[str, Any]] | None = None,
) -> str:
    turns = thread.get("turns")
    if turns is None and list_turns is not None:
        turns = []
    if not isinstance(turns, list):
        raise AdapterError("CODEX_ACTIVE_WRITER_UNRESOLVED", "active thread omitted its turns")
    active = {
        turn.get("id")
        for turn in turns
        if isinstance(turn, Mapping) and turn.get("status") in {"inProgress", "active"}
        and isinstance(turn.get("id"), str)
        and turn.get("id")
    }
    if len(active) > 1:
        raise AdapterError(
            "CODEX_ACTIVE_WRITER_UNRESOLVED",
            "active thread exposed multiple active turns",
        )
    if len(active) == 1:
        return next(iter(active))
    if list_turns is None:
        raise AdapterError(
            "CODEX_ACTIVE_WRITER_UNRESOLVED",
            "active thread did not expose exactly one active turn",
        )
    cursor: str | None = None
    seen_cursors: set[str] = set()
    for _ in range(100):
        page = list_turns(cursor)
        data = page.get("data")
        next_cursor = page.get("nextCursor")
        if not isinstance(data, list) or (
            next_cursor is not None and (not isinstance(next_cursor, str) or not next_cursor)
        ):
            raise AdapterError(
                "CODEX_ACTIVE_WRITER_UNRESOLVED", "active-turn page is malformed"
            )
        active.update(
            turn.get("id")
            for turn in data
            if isinstance(turn, Mapping)
            and turn.get("status") in {"inProgress", "active"}
            and isinstance(turn.get("id"), str)
            and turn.get("id")
        )
        if len(active) > 1:
            raise AdapterError(
                "CODEX_ACTIVE_WRITER_UNRESOLVED",
                "paginated thread exposed multiple active turns",
            )
        if next_cursor is None:
            break
        if next_cursor in seen_cursors:
            raise AdapterError(
                "CODEX_ACTIVE_WRITER_UNRESOLVED", "active-turn pagination repeated a cursor"
            )
        seen_cursors.add(next_cursor)
        cursor = next_cursor
    else:
        raise AdapterError(
            "CODEX_ACTIVE_WRITER_UNRESOLVED", "active-turn pagination exceeded its bound"
        )
    if len(active) != 1:
        raise AdapterError(
            "CODEX_ACTIVE_WRITER_UNRESOLVED",
            "paginated thread did not expose exactly one active turn",
        )
    return next(iter(active))


def _active_writer_error(
    attempt: Attempt,
    envelope: Envelope,
    thread_id: str,
    thread: Mapping[str, Any],
    *,
    list_turns: Callable[[str | None], Mapping[str, Any]] | None = None,
) -> AdapterError:
    turn_id = active_turn_id(thread, list_turns=list_turns)
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
    return AdapterError(
        "CODEX_ACTIVE_WRITER",
        f"Supervisor thread has active writer turn {turn_id}",
    )


def _is_initialize_writer_conflict(error: AdapterError, client: JsonRpcProcess) -> bool:
    evidence = f"{error}\n" + "\n".join(client.stderr_lines)
    lowered = evidence.lower()
    return "thread-store conflict" in lowered and "already has an active writer" in lowered


def resolve_codex_command(
    command: list[str],
    *,
    attempt: Attempt | None = None,
    thread_id: str | None = None,
) -> list[str]:
    """Resolve a moved Codex Desktop executable without changing endpoint identity."""

    requested = command[0]
    requested_path = Path(requested)
    if requested_path.is_file():
        return list(command)
    if not requested_path.is_absolute():
        found = shutil.which(requested)
        if found:
            return [found, *command[1:]]
    if requested_path.name.lower() not in {"codex", "codex.exe"}:
        raise AdapterError("CODEX_EXECUTABLE_MISSING", "configured executable does not exist")
    resolved = shutil.which("codex.exe") or shutil.which("codex")
    if not resolved or not Path(resolved).is_file():
        raise AdapterError("CODEX_EXECUTABLE_MISSING", "current Codex executable is unavailable")
    rebound = [str(Path(resolved).resolve()), *command[1:]]
    if attempt is not None:
        attempt.write_json_once(
            "command-rebind.json",
            {
                "schema_version": "slk.codex-command-rebind/v1",
                "requested_executable": requested,
                "resolved_executable": rebound[0],
                "thread_id": thread_id,
                "reason": "configured_codex_executable_missing",
            },
        )
    return rebound


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
        if set(address) not in (ADDRESS_FIELDS, ADDRESS_FIELDS | {"desktop"}):
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
        if "desktop" in address:
            from .codex_desktop import validate_desktop_address
            validate_desktop_address(address)

    def _prompt(self, envelope: Envelope, attempt: Attempt | None = None) -> str:
        value = json.dumps(asdict(envelope), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        prompt = (
            "SLK cross-Agent delivery. Treat the closed envelope below as the current assigned work, "
            "not as background or a status-only message. Do not locate another task by title.\n"
            f"<slk-transport-envelope>{value}</slk-transport-envelope>"
        )
        if (attempt is not None and os.environ.get("SLK_TRANSPORT_ROLE_HOST")
            and envelope.payload_type in {"D1_FAILURE_ESCALATION", "D2_READY"}):
            operation = "rework" if envelope.payload_type == "D1_FAILURE_ESCALATION" else "d2"
            prompt += "\nThe original Supervisor makes the engineering decision; do not repeat or replace Checker D1. "
            prompt += "Existing output is always saved; it is not itself a command. For an explicit state/handoff action, use the bound submit_command in this same Session. Never consume sealed credentials or pretend to be Checker. "
            contract = ({"d1_failure_event_id": envelope.payload.get("d1_failure_event_id"),
                "failed_candidate_sha256": envelope.payload.get("failed_candidate_sha256"),
                "rework_round": envelope.payload.get("rework_round"),
                "investigation_mode": "your chosen bounded investigation",
                "guidance": "your engineering guidance; report fields are not host-reviewed"}
                if operation == "rework" else {"verdict": "your explicit PASS, FAIL or INCOMPLETE"})
            descriptor: dict[str, Any] = {"result_path": str(attempt.root / "supervisor-result.json"),
                "schema_version": "slk.supervisor-result/v1", "source_message_id": envelope.message_id,
                "operation": operation, "decision_contract": contract}
            binding_value = os.environ.get("SLK_TRANSPORT_ROLE_HOST")
            binding_digest = os.environ.get("SLK_TRANSPORT_ROLE_HOST_SHA256")
            try:
                binding_path = Path(binding_value or "")
                if (not binding_path.is_absolute() or not binding_path.is_file()
                    or hashlib.sha256(binding_path.read_bytes()).hexdigest() != binding_digest):
                    raise ValueError("role host binding is unavailable")
                binding = json.loads(binding_path.read_text(encoding="utf-8-sig"))
                transport = binding["transport_command"]
                if not isinstance(transport, list) or not transport or not all(
                    isinstance(item, str) and item for item in transport
                ):
                    raise ValueError("transport command is invalid")
                descriptor["submit_command"] = [*transport, "submit-supervisor-decision",
                    "--binding", str(binding_path), "--sha256", str(binding_digest),
                    "--source-attempt", str(attempt.root)]
                prompt += "After atomically writing the result, immediately run submit_command in this same Session; do not wait for the whole turn to end. "
            except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
                pass
            prompt += "Action API uses operation and decision, with source_message_id binding the incoming work. Other report fields are not reviewed. result_path and submit_command are instructions, not result fields. "
            prompt += json.dumps(descriptor, ensure_ascii=False)
        return prompt

    def deliver(self, endpoint: Endpoint, envelope: Envelope, attempt: Attempt) -> DeliveryResult:
        self.validate_address(endpoint)
        address = endpoint.address
        if "desktop" in address:
            from .codex_desktop import deliver_desktop
            return deliver_desktop(endpoint, envelope, attempt, self._prompt(envelope, attempt))
        from .codex_desktop import _prepare_prompt
        prompt = _prepare_prompt(self._prompt(envelope, attempt), envelope, attempt)
        command = resolve_codex_command(
            list(address["command"]), attempt=attempt, thread_id=str(address["thread_id"])
        )
        thread_id = str(address["thread_id"])
        cwd = Path(str(address["cwd"]))
        startup_timeout = _positive_seconds(address["startup_timeout_seconds"], "startup_timeout_seconds")
        turn_timeout = _positive_seconds(address["turn_timeout_seconds"], "turn_timeout_seconds")
        client: JsonRpcProcess | None = None
        try:
            client = JsonRpcProcess(command, cwd)
            try:
                client.request(
                    1,
                    "initialize",
                    {
                        "clientInfo": {
                            "name": "slk_transport",
                            "title": "SLK Transport",
                            "version": "4.4.3",
                        }
                    },
                    startup_timeout,
                )
            except AdapterError as error:
                if _is_initialize_writer_conflict(error, client):
                    raise AdapterError(
                        "CODEX_ACTIVE_WRITER_UNRESOLVED",
                        "Codex Desktop owns the thread writer but the independent process cannot prove its turn",
                    ) from error
                raise
            client.notify("initialized", {})
            request_id = 2

            def read_thread() -> Mapping[str, Any]:
                nonlocal request_id
                result = client.request(
                    request_id,
                    "thread/read",
                    {"threadId": thread_id, "includeTurns": False},
                    startup_timeout,
                )
                request_id += 1
                return result

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

            read = read_thread()
            thread = read.get("thread")
            if not isinstance(thread, Mapping) or thread.get("id") != thread_id:
                raise AdapterError("CODEX_THREAD_ID_MISMATCH", "Codex read a different thread")
            status = thread.get("status")
            status_type = status.get("type") if isinstance(status, Mapping) else None
            if status_type in {"active", "notLoaded"}:
                raise _active_writer_error(
                    attempt, envelope, thread_id, thread, list_turns=list_turns
                )
            if status_type != "idle":
                raise AdapterError(
                    "CODEX_THREAD_TERMINAL", f"Codex target thread has terminal state {status_type}"
                )

            notification_start = len(client.messages)
            started_response = client.request(
                request_id,
                "turn/start",
                {
                    "threadId": thread_id,
                    "input": [{"type": "text", "text": prompt}],
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
                make_native_start(
                    adapter=endpoint.adapter,
                    run_id=envelope.run_id,
                    cell_id=envelope.cell_id,
                    message_id=envelope.message_id,
                    request_sha256=envelope.payload_sha256,
                    native_request_sha256=hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
                    native_task_kind="codex-turn",
                    native_task_id=f"{started['threadId']}:{turn_id}",
                    native_task_status="RUNNING",
                    pid=client.pid,
                ),
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
