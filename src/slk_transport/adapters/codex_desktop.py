"""Codex adapter's opt-in native Desktop entry; no writer takeover or daemon."""
from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any, Mapping
from xml.sax.saxutils import escape

from .base import AdapterError
from ..contracts import ContractError, DeliveryResult, Endpoint, Envelope, RESULT_SCHEMA, SHA256
from ..evidence import Attempt
from ..jsonrpc import JsonRpcProcess
from ..native_activity import (
    TASK_ACTIVITY_SCHEMA,
    _atomic_json,
    make_native_start,
    utc_now,
    validate_native_start,
)


READBACK_ANCHOR_FIELDS = {
    "schema_version", "thread_id", "host_id", "caller_thread_id", "message_id",
    "prompt_sha256", "previous_turn_ids", "previous_item_ids", "active_turn_ids",
}


def _checker_return(endpoint: Endpoint, envelope: Envelope) -> bool:
    return (endpoint.role == "supervisor" and endpoint.state == "active"
            and endpoint.run_id == getattr(envelope, "run_id", None)
            and endpoint.role_instance_id == getattr(envelope, "receiver_role_instance_id", None)
            and endpoint.endpoint_version == getattr(envelope, "receiver_endpoint_version", None)
            and getattr(envelope, "sender_role", None) == "checker"
            and getattr(envelope, "receiver_role", None) == "supervisor"
            and getattr(envelope, "payload_type", None) in {
                "D1_FAILURE_ESCALATION", "D1_INCOMPLETE_ESCALATION", "D2_READY"})


def _valid_caller(endpoint: Endpoint, envelope: Envelope, caller: Any) -> bool:
    return (isinstance(caller, str) and bool(caller) and caller == caller.strip()
            and (caller == endpoint.address["desktop"]["caller_thread_id"] or _checker_return(endpoint, envelope)))


def _executor(endpoint: Endpoint, envelope: Envelope) -> str:
    caller = os.environ.get("CODEX_THREAD_ID")
    if (not _valid_caller(endpoint, envelope, caller) or not os.environ.get("CODEX_APP_TOOLS_PIPE_PATH")
        or os.environ.get("CODEX_INTERNAL_ORIGINATOR_OVERRIDE") != "Codex Desktop"):
        raise AdapterError("CODEX_DESKTOP_HOST_UNAVAILABLE", "the prepared Desktop executor capability was not inherited")
    return str(caller)


def validate_desktop_address(address: Mapping[str, Any]) -> None:
    binding = address["desktop"]
    if (not isinstance(binding, Mapping)
        or set(binding) != {"caller_thread_id", "model", "reasoning_effort", "plugin_sha256"}
        or any(not isinstance(binding[k], str) or not binding[k] or binding[k] != binding[k].strip() for k in binding)
        or binding["reasoning_effort"] not in {"high", "xhigh"}
        or not SHA256.fullmatch(binding["plugin_sha256"])):
        raise AdapterError("CODEX_ADDRESS_INVALID", "Desktop binding must be exact and versioned by plugin hash")
    command = address["command"]
    if len(command) != 2 or not all(Path(p).is_absolute() and Path(p).is_file() for p in command):
        raise AdapterError("CODEX_ADDRESS_INVALID", "Desktop command must name installed runtime and plugin files")
    if hashlib.sha256(Path(command[1]).read_bytes()).hexdigest() != binding["plugin_sha256"]:
        raise AdapterError("CODEX_DESKTOP_PLUGIN_CHANGED", "prepared Desktop plugin changed; repeat readiness")


class DesktopClient(JsonRpcProcess):
    def _receive(self, timeout: float) -> dict[str, Any]:
        value = super()._receive(timeout)
        # Desktop uses direct request results, not App Server notification history.
        del self.messages[:-1]
        return value

    def send(self, value: Mapping[str, Any]) -> None:
        super().send({"jsonrpc": "2.0", **value})

    def call(self, request_id: int, name: str, arguments: Mapping[str, Any], caller: str, timeout: float) -> Mapping[str, Any]:
        result = self.request(request_id, "tools/call", {"name": name, "arguments": dict(arguments),
            "_meta": {"codex_thread_id": caller}}, timeout)
        content = result.get("content")
        if (result.get("isError") is not False or not isinstance(content, list) or len(content) != 1
            or not isinstance(content[0], Mapping) or content[0].get("type") != "text"):
            raise AdapterError("CODEX_DESKTOP_TOOL_FAILED", f"Desktop {name} did not return one successful text result")
        try:
            value = json.loads(content[0]["text"])
        except (KeyError, ValueError, TypeError) as error:
            raise AdapterError("CODEX_DESKTOP_PROTOCOL_INVALID", "Desktop result is not readable JSON") from error
        if not isinstance(value, Mapping):
            raise AdapterError("CODEX_DESKTOP_PROTOCOL_INVALID", "Desktop result is not an object")
        return value


def _view(value: Mapping[str, Any], endpoint: Endpoint) -> tuple[Mapping[str, Any], list]:
    thread, turns = value.get("thread"), value.get("turns")
    if (not isinstance(thread, Mapping) or thread.get("id") != endpoint.address["thread_id"]
        or thread.get("hostId") != endpoint.host_id
        or not isinstance(thread.get("cwd"), str)
        or Path(thread["cwd"]).resolve() != Path(str(endpoint.address["cwd"])).resolve()):
        raise AdapterError("CODEX_THREAD_ID_MISMATCH", "Desktop readback differs from the prepared thread/host/workspace")
    if not isinstance(turns, list) or not all(isinstance(t, Mapping) and isinstance(t.get("id"), str) for t in turns):
        raise AdapterError("CODEX_DESKTOP_PROTOCOL_INVALID", "Desktop omitted native turn identities")
    if (not isinstance(thread.get("status"), Mapping)
        or any(not isinstance(t.get("items"), list)
               or not all(isinstance(i, Mapping) for i in t["items"]) for t in turns)):
        raise AdapterError("CODEX_DESKTOP_PROTOCOL_INVALID", "Desktop status or native items are malformed")
    return thread, turns


def _read_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AdapterError("CODEX_DESKTOP_READBACK_DRIFT", f"{label} is missing or unreadable") from exc
    if not isinstance(value, dict):
        raise AdapterError("CODEX_DESKTOP_READBACK_DRIFT", f"{label} is not an object")
    return value


def _write_or_match(attempt: Attempt, name: str, value: Mapping[str, Any]) -> None:
    path = attempt.root / name
    if path.exists():
        if _read_object(path, name) != dict(value):
            raise AdapterError("CODEX_DESKTOP_READBACK_AMBIGUOUS", f"{name} changed native identity")
        return
    attempt.write_json_once(name, value)


def _matching_items(
    turns: list[Mapping[str, Any]],
    *,
    previous: set[str],
    previous_items: set[str],
    active: set[str],
    expected: str,
) -> list[tuple[Mapping[str, Any], Mapping[str, Any]]]:
    matches = []
    for turn in turns:
        for item in turn.get("items", []):
            output = item.get("output", {}) if isinstance(item, Mapping) else {}
            if ((turn["id"] not in previous or turn["id"] in active)
                and isinstance(item.get("id"), str) and item["id"] not in previous_items
                and item.get("type") == "functionCallOutput" and item.get("name") == "send_message_to_thread"
                and item.get("namespace") == "codex_app" and isinstance(output, Mapping)
                and output.get("truncated") is False and output.get("text") == expected):
                matches.append((turn, item))
    return matches


def _readback_result(
    endpoint: Endpoint,
    envelope: Envelope,
    attempt: Attempt,
    turn: Mapping[str, Any],
    item: Mapping[str, Any],
    prompt_sha256: str,
    caller: str,
) -> DeliveryResult:
    if turn.get("status") not in {"completed", "inProgress", "active"}:
        raise AdapterError("CODEX_TURN_FAILED", "Desktop native turn did not complete successfully")
    target = str(endpoint.address["thread_id"])
    identity = f"{target}:{turn['id']}:{item['id']}"
    proof = {
        "thread_id": target,
        "turn_id": turn["id"],
        "turn_status": turn["status"],
        "platform_item_id": item["id"],
        "caller_thread_id": caller,
        "message_id": envelope.message_id,
        "platform_item": dict(item),
    }
    _write_or_match(attempt, "desktop-readback.json", proof)
    started = make_native_start(
        adapter=endpoint.adapter,
        run_id=envelope.run_id,
        cell_id=envelope.cell_id,
        message_id=envelope.message_id,
        request_sha256=envelope.payload_sha256,
        native_request_sha256=prompt_sha256,
        native_task_kind="codex-desktop-turn",
        native_task_id=identity,
        native_task_status="IDLE" if turn.get("status") == "completed" else "RUNNING",
        pid=os.getpid(),
    )
    _write_or_match(attempt, "started.json", started)
    _atomic_json(attempt.root / "native-activity.json", {
        "schema_version": TASK_ACTIVITY_SCHEMA, "adapter": endpoint.adapter,
        "run_id": envelope.run_id, "cell_id": envelope.cell_id, "message_id": envelope.message_id,
        "native_task_id": identity,
        "status": "COMPLETED" if turn["status"] == "completed" else "RUNNING",
        "sequence": 1, "observed_at": utc_now(),
        "last_event": {"kind": "DESKTOP_TURN_OBSERVED", "sequence": 1}, "waiting_on": None,
    })
    return DeliveryResult(
        RESULT_SCHEMA, envelope.message_id, envelope.run_id, endpoint.adapter,
        "completed" if turn["status"] == "completed" else "started",
        {"thread_id": target, "turn_id": turn["id"], "platform_item_id": item["id"],
         "turn_status": turn["status"]}, None,
        ("started.json", "desktop-send.json", "desktop-readback.json"),
    )


def validate_late_desktop_start(
    endpoint: Endpoint, envelope: Envelope, attempt: Attempt,
) -> DeliveryResult | None:
    """Accept only the exact readback that arrived after one immutable readback failure."""
    failed_path = attempt.root / "failed.json"
    proof_path = attempt.root / "desktop-readback.json"
    started_path = attempt.root / "started.json"
    if not failed_path.is_file() or (not proof_path.exists() and not started_path.exists()):
        return None
    required = {
        "endpoint.json", "envelope.json", "failed.json", "desktop-prompt.json",
        "desktop-readback-anchor.json", "desktop-send.json", "desktop-readback.json",
        "started.json",
    }
    if (attempt.root / "completed.json").exists() or any(
        not (attempt.root / name).is_file() for name in required
    ):
        raise AdapterError(
            "CODEX_DESKTOP_LATE_START_INVALID", "late Desktop start evidence is incomplete"
        )
    try:
        saved_endpoint = Endpoint.from_dict(_read_object(attempt.root / "endpoint.json", "endpoint"))
        saved_envelope = Envelope.from_dict(_read_object(attempt.root / "envelope.json", "envelope"))
        failed = DeliveryResult.from_dict(_read_object(attempt.root / "failed.json", "failed result"))
    except (ContractError, KeyError, TypeError, ValueError) as exc:
        raise AdapterError(
            "CODEX_DESKTOP_LATE_START_INVALID", "late Desktop terminal identity is invalid"
        ) from exc
    expected_failure_evidence = tuple(sorted((
        "accepted.json", "desktop-prompt.json", "desktop-readback-anchor.json",
        "desktop-send.json", "endpoint.json", "envelope.json",
    ) + tuple(name for name in ("desktop-target-observation.json", "desktop-target-observation-latest.json")
              if (attempt.root / name).is_file())))
    if (
        saved_endpoint != endpoint
        or saved_envelope != envelope
        or failed.message_id != envelope.message_id
        or failed.run_id != envelope.run_id
        or failed.adapter != endpoint.adapter
        or failed.status != "failed"
        or failed.native_identity
        or failed.error_code != "CODEX_DESKTOP_READBACK_UNPROVED"
        or failed.evidence != expected_failure_evidence
    ):
        raise AdapterError(
            "CODEX_DESKTOP_LATE_START_INVALID", "late Desktop failure identity changed"
        )

    validate_desktop_address(endpoint.address)
    address, binding = endpoint.address, endpoint.address["desktop"]
    target = str(address["thread_id"])
    prompt = _read_object(attempt.root / "desktop-prompt.json", "Desktop prompt evidence")
    if (
        set(prompt) != {"message_id", "prompt"}
        or prompt.get("message_id") != envelope.message_id
        or not isinstance(prompt.get("prompt"), str)
    ):
        raise AdapterError(
            "CODEX_DESKTOP_LATE_START_INVALID", "late Desktop prompt identity changed"
        )
    prompt_sha256 = hashlib.sha256(prompt["prompt"].encode()).hexdigest()
    anchor = _read_object(attempt.root / "desktop-readback-anchor.json", "Desktop readback anchor")
    caller = anchor.get("caller_thread_id")
    if (
        set(anchor) != READBACK_ANCHOR_FIELDS
        or anchor.get("schema_version") != "slk.desktop-readback-anchor/v1"
        or anchor.get("thread_id") != target
        or anchor.get("host_id") != endpoint.host_id
        or not _valid_caller(endpoint, envelope, caller)
        or anchor.get("message_id") != envelope.message_id
        or anchor.get("prompt_sha256") != prompt_sha256
        or any(
            not isinstance(anchor.get(key), list)
            or not all(isinstance(value, str) for value in anchor[key])
            for key in ("previous_turn_ids", "previous_item_ids", "active_turn_ids")
        )
    ):
        raise AdapterError(
            "CODEX_DESKTOP_LATE_START_INVALID", "late Desktop readback anchor changed"
        )
    sent = _read_object(attempt.root / "desktop-send.json", "Desktop send evidence")
    if (
        sent.get("thread_id") != target
        or sent.get("caller_thread_id") != caller
        or sent.get("message_id") != envelope.message_id
        or sent.get("prompt_sha256") != prompt_sha256
        or not isinstance(sent.get("result"), Mapping)
        or sent["result"].get("threadId") != target
    ):
        raise AdapterError(
            "CODEX_DESKTOP_LATE_START_INVALID", "late Desktop accepted send changed"
        )
    proof = _read_object(proof_path, "Desktop readback proof")
    item = proof.get("platform_item")
    if (
        set(proof) != {
            "thread_id", "turn_id", "turn_status", "platform_item_id",
            "caller_thread_id", "message_id", "platform_item",
        }
        or proof.get("thread_id") != target
        or proof.get("caller_thread_id") != caller
        or proof.get("message_id") != envelope.message_id
        or proof.get("turn_status") not in {"completed", "inProgress", "active"}
        or not isinstance(proof.get("turn_id"), str)
        or not isinstance(proof.get("platform_item_id"), str)
        or not isinstance(item, Mapping)
        or item.get("id") != proof.get("platform_item_id")
    ):
        raise AdapterError(
            "CODEX_DESKTOP_LATE_START_INVALID", "late Desktop readback identity changed"
        )
    native_id = f"{target}:{proof['turn_id']}:{proof['platform_item_id']}"
    try:
        started = validate_native_start(
            started_path,
            adapter=endpoint.adapter,
            run_id=envelope.run_id,
            cell_id=envelope.cell_id,
            message_id=envelope.message_id,
            request_sha256=envelope.payload_sha256,
            native_request_sha256=prompt_sha256,
        )
    except (OSError, KeyError, ValueError) as exc:
        raise AdapterError(
            "CODEX_DESKTOP_LATE_START_INVALID", "late Desktop native start changed"
        ) from exc
    if (
        started["native_task"]["kind"] != "codex-desktop-turn"
        or started["native_task"]["id"] != native_id
    ):
        raise AdapterError(
            "CODEX_DESKTOP_LATE_START_INVALID", "late Desktop native task changed"
        )
    return DeliveryResult(
        RESULT_SCHEMA, envelope.message_id, envelope.run_id, endpoint.adapter,
        "completed" if proof["turn_status"] == "completed" else "started",
        {"thread_id": target, "turn_id": proof["turn_id"],
         "platform_item_id": proof["platform_item_id"], "turn_status": proof["turn_status"]},
        None, ("started.json", "desktop-send.json", "desktop-readback.json"),
    )


def consume_desktop_readback(
    endpoint: Endpoint,
    envelope: Envelope,
    attempt: Attempt,
    prompt: str | None = None,
) -> DeliveryResult:
    """Read the original Desktop delivery once; never send or create a replacement turn."""
    validate_desktop_address(endpoint.address)
    address, binding = endpoint.address, endpoint.address["desktop"]
    reader, target = _executor(endpoint, envelope), address["thread_id"]
    if prompt is None:
        prompt_record = _read_object(attempt.root / "desktop-prompt.json", "Desktop prompt evidence")
        if (set(prompt_record) != {"message_id", "prompt"}
            or prompt_record.get("message_id") != envelope.message_id
            or not isinstance(prompt_record.get("prompt"), str)):
            raise AdapterError("CODEX_DESKTOP_READBACK_DRIFT", "Desktop prompt evidence changed identity")
        prompt = prompt_record["prompt"]
    prompt_sha256 = hashlib.sha256(prompt.encode()).hexdigest()
    anchor = _read_object(attempt.root / "desktop-readback-anchor.json", "Desktop readback anchor")
    caller = anchor.get("caller_thread_id")
    if (set(anchor) != READBACK_ANCHOR_FIELDS or anchor.get("schema_version") != "slk.desktop-readback-anchor/v1"
        or anchor.get("thread_id") != target or anchor.get("host_id") != endpoint.host_id
        or not _valid_caller(endpoint, envelope, caller) or anchor.get("message_id") != envelope.message_id
        or anchor.get("prompt_sha256") != prompt_sha256
        or any(not isinstance(anchor.get(key), list) or not all(isinstance(v, str) for v in anchor[key])
               for key in ("previous_turn_ids", "previous_item_ids", "active_turn_ids"))):
        raise AdapterError("CODEX_DESKTOP_READBACK_DRIFT", "Desktop readback anchor changed identity")
    sent = _read_object(attempt.root / "desktop-send.json", "Desktop send evidence")
    if (sent.get("thread_id") != target or sent.get("caller_thread_id") != caller
        or sent.get("message_id") != envelope.message_id or sent.get("prompt_sha256") != prompt_sha256
        or not isinstance(sent.get("result"), Mapping) or sent["result"].get("threadId") != target):
        raise AdapterError("CODEX_DESKTOP_READBACK_DRIFT", "Desktop accepted-send evidence changed identity")
    proof_path = attempt.root / "desktop-readback.json"
    if proof_path.is_file():
        proof = _read_object(proof_path, "Desktop readback proof")
        item = proof.get("platform_item")
        turn_status = proof.get("turn_status")
        if (proof.get("thread_id") != target or proof.get("caller_thread_id") != caller
            or proof.get("message_id") != envelope.message_id or not isinstance(item, Mapping)
            or turn_status not in {"completed", "inProgress", "active"}):
            raise AdapterError("CODEX_DESKTOP_READBACK_AMBIGUOUS", "saved Desktop readback changed identity")
        native_id = f"{target}:{proof.get('turn_id')}:{proof.get('platform_item_id')}"
        try:
            started = validate_native_start(
                attempt.root / "started.json", adapter=endpoint.adapter,
                run_id=envelope.run_id, cell_id=envelope.cell_id, message_id=envelope.message_id,
                request_sha256=envelope.payload_sha256, native_request_sha256=prompt_sha256,
            )
            if (started["native_task"]["kind"] != "codex-desktop-turn"
                or started["native_task"]["id"] != native_id):
                raise ValueError("saved native start changed identity")
        except (OSError, KeyError, ValueError) as exc:
            raise AdapterError("CODEX_DESKTOP_READBACK_AMBIGUOUS", "saved native start changed identity") from exc
        return DeliveryResult(
            RESULT_SCHEMA, envelope.message_id, envelope.run_id, endpoint.adapter,
            "completed" if turn_status == "completed" else "started",
            {"thread_id": target, "turn_id": proof["turn_id"],
             "platform_item_id": proof["platform_item_id"], "turn_status": turn_status}, None,
            ("started.json", "desktop-send.json", "desktop-readback.json"),
        )
    expected = f"<codex_delegation>\n  <source_thread_id>{escape(caller)}</source_thread_id>\n  <input>{escape(prompt)}</input>\n</codex_delegation>"
    timeout = float(address["startup_timeout_seconds"])
    client = DesktopClient(list(address["command"]), Path(str(address["cwd"])))
    try:
        client.request(1, "initialize", {"protocolVersion": "2024-11-05", "capabilities": {},
            "clientInfo": {"name": "slk_transport_desktop_readback", "version": "4.4.2"}}, timeout)
        client.notify("notifications/initialized", {})
        catalog = client.request(2, "tools/list", {}, timeout)
        if "read_thread" not in {t.get("name") for t in catalog.get("tools", []) if isinstance(t, Mapping)}:
            raise AdapterError("CODEX_DESKTOP_HOST_UNAVAILABLE", "installed Desktop plugin lacks read_thread")
        args = {"threadId": target, "hostId": endpoint.host_id, "turnLimit": 2,
                "includeOutputs": True, "maxOutputCharsPerItem": len(expected) + 512}
        view = client.call(3, "read_thread", args, reader, timeout)
        _, turns = _view(view, endpoint)
        matches = _matching_items(turns, previous=set(anchor["previous_turn_ids"]),
            previous_items=set(anchor["previous_item_ids"]), active=set(anchor["active_turn_ids"]),
            expected=expected)
        if len(matches) > 1:
            raise AdapterError("CODEX_DESKTOP_READBACK_AMBIGUOUS", "multiple native items claim this exact delivery")
        if not matches:
            raise AdapterError("CODEX_DESKTOP_READBACK_UNPROVED", "original accepted send still lacks exact native proof; do not resend")
        return _readback_result(endpoint, envelope, attempt, *matches[0], prompt_sha256, str(caller))
    except TimeoutError as error:
        raise AdapterError("CODEX_RPC_TIMEOUT", "Desktop native readback timed out; do not resend") from error
    finally:
        client.close()


def deliver_desktop(endpoint: Endpoint, envelope: Envelope, attempt: Attempt, prompt: str,
                    *, wait_for_completion: bool = True) -> DeliveryResult:
    address, binding = endpoint.address, endpoint.address["desktop"]
    caller, target = _executor(endpoint, envelope), address["thread_id"]
    expected = f"<codex_delegation>\n  <source_thread_id>{escape(caller)}</source_thread_id>\n  <input>{escape(prompt)}</input>\n</codex_delegation>"
    timeout = float(address["startup_timeout_seconds"])
    client = DesktopClient(list(address["command"]), Path(str(address["cwd"])))
    try:
        client.request(1, "initialize", {"protocolVersion": "2024-11-05", "capabilities": {},
            "clientInfo": {"name": "slk_transport_desktop", "version": "4.4.2"}}, timeout)
        client.notify("notifications/initialized", {})
        catalog = client.request(2, "tools/list", {}, timeout)
        if not {"read_thread", "send_message_to_thread"}.issubset({t.get("name") for t in catalog.get("tools", []) if isinstance(t, Mapping)}):
            raise AdapterError("CODEX_DESKTOP_HOST_UNAVAILABLE", "installed Desktop plugin lacks the required native tools")
        args = {"threadId": target, "hostId": endpoint.host_id, "turnLimit": 2,
                "includeOutputs": True, "maxOutputCharsPerItem": len(expected) + 512}
        before = client.call(3, "read_thread", args, caller, timeout)
        thread, turns = _view(before, endpoint)
        status = thread.get("status", {}).get("type")
        active = [t["id"] for t in turns if t.get("status") in {"inProgress", "active"}]
        observation = {
            "thread_id": target, "host_id": endpoint.host_id, "caller_thread_id": caller,
            "thread_status": status, "turns": [{"id": t["id"], "status": t.get("status")} for t in turns],
            "observed_at": utc_now(),
        }
        if (attempt.root / "desktop-target-observation.json").exists():
            _atomic_json(attempt.root / "desktop-target-observation-latest.json", observation)
        else:
            attempt.write_json_once("desktop-target-observation.json", observation)
        if status not in {"idle", "active"}:
            code = "CODEX_THREAD_TERMINAL" if status in {"completed", "failed", "cancelled", "interrupted", "archived"} else "CODEX_THREAD_STATE_UNKNOWN"
            raise AdapterError(code, "Desktop returned target state " + str(status))
        if (status == "active" and len(active) != 1) or (status == "idle" and active):
            raise AdapterError("CODEX_ACTIVE_WRITER_UNRESOLVED", "Desktop active turn identity is ambiguous")
        previous = {t["id"] for t in turns}
        previous_items = {i.get("id") for t in turns for i in t["items"] if isinstance(i.get("id"), str)}
        attempt.write_json_once("desktop-readback-anchor.json", {
            "schema_version": "slk.desktop-readback-anchor/v1", "thread_id": target,
            "host_id": endpoint.host_id, "caller_thread_id": caller,
            "message_id": envelope.message_id, "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
            "previous_turn_ids": sorted(previous), "previous_item_ids": sorted(previous_items),
            "active_turn_ids": sorted(active),
        })
        attempt.write_json_once("desktop-prompt.json", {
            "message_id": envelope.message_id, "prompt": prompt,
        })
        sent = client.call(4, "send_message_to_thread", {"threadId": target, "hostId": endpoint.host_id,
            "model": binding["model"], "thinking": binding["reasoning_effort"], "prompt": prompt}, caller, timeout)
        attempt.write_json_once("desktop-send.json", {"thread_id": target, "caller_thread_id": caller,
            "message_id": envelope.message_id, "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
            "requested_model": binding["model"], "requested_effort": binding["reasoning_effort"], "result": dict(sent)})
        if sent.get("threadId") != target:
            raise AdapterError("CODEX_THREAD_ID_MISMATCH", "Desktop acknowledged a different target")
        deadline, request_id, proven = time.monotonic() + timeout, 5, None
        while True:
            view = client.call(request_id, "read_thread", args, caller, timeout)
            request_id += 1
            _, turns = _view(view, endpoint)
            matches = []
            for turn in turns:
                for item in turn.get("items", []):
                    output = item.get("output", {}) if isinstance(item, Mapping) else {}
                    if ((turn["id"] not in previous or turn["id"] in active)
                        and isinstance(item.get("id"), str) and item["id"] not in previous_items
                        and item.get("type") == "functionCallOutput" and item.get("name") == "send_message_to_thread"
                        and item.get("namespace") == "codex_app" and isinstance(output, Mapping)
                        and output.get("truncated") is False and output.get("text") == expected):
                        matches.append((turn, item))
            if len(matches) > 1:
                raise AdapterError("CODEX_DESKTOP_READBACK_AMBIGUOUS", "multiple native items claim this exact delivery")
            if matches:
                turn, item = matches[0]
                if turn.get("status") not in {"completed", "inProgress", "active"}:
                    raise AdapterError("CODEX_TURN_FAILED", "Desktop native turn did not complete successfully")
                identity = (turn["id"], item["id"])
                if proven is not None and proven != identity:
                    raise AdapterError("CODEX_DESKTOP_READBACK_AMBIGUOUS", "delivery native identity changed")
                if proven is None:
                    proven = identity
                    proof = {"thread_id": target, "turn_id": turn["id"], "turn_status": turn["status"],
                             "platform_item_id": item["id"],
                             "caller_thread_id": caller, "message_id": envelope.message_id, "platform_item": dict(item)}
                    attempt.write_json_once("desktop-readback.json", proof)
                    attempt.write_json_once("started.json", make_native_start(adapter=endpoint.adapter,
                        run_id=envelope.run_id, cell_id=envelope.cell_id, message_id=envelope.message_id,
                        request_sha256=envelope.payload_sha256, native_request_sha256=hashlib.sha256(prompt.encode()).hexdigest(),
                        native_task_kind="codex-desktop-turn", native_task_id=f"{target}:{turn['id']}:{item['id']}",
                        native_task_status="IDLE" if turn.get("status") == "completed" else "RUNNING", pid=os.getpid()))
                _atomic_json(attempt.root / "native-activity.json", {
                    "schema_version": TASK_ACTIVITY_SCHEMA, "adapter": endpoint.adapter,
                    "run_id": envelope.run_id, "cell_id": envelope.cell_id, "message_id": envelope.message_id,
                    "native_task_id": f"{target}:{turn['id']}:{item['id']}",
                    "status": "COMPLETED" if turn["status"] == "completed" else "RUNNING",
                    "sequence": request_id, "observed_at": utc_now(),
                    "last_event": {"kind": "DESKTOP_TURN_OBSERVED", "sequence": request_id}, "waiting_on": None})
                if turn.get("status") == "completed" or not wait_for_completion:
                    return DeliveryResult(RESULT_SCHEMA, envelope.message_id, envelope.run_id, endpoint.adapter,
                        "completed" if turn["status"] == "completed" else "started",
                        {"thread_id": target, "turn_id": turn["id"], "platform_item_id": item["id"], "turn_status": turn["status"]}, None,
                        ("started.json", "desktop-send.json", "desktop-readback.json"))
            now = time.monotonic()
            if proven is None and now >= deadline:
                raise AdapterError("CODEX_DESKTOP_READBACK_UNPROVED", "accepted send lacks exact native delivery/turn proof; do not resend blindly")
            # The transport bounds startup/RPCs, not an already proven engineering turn.
            # Residency alarms and recovery decisions remain with Temporal/Supervisor.
            time.sleep(.5 if proven else min(.5, max(.001, deadline - now)))
    except TimeoutError as error:
        raise AdapterError("CODEX_RPC_TIMEOUT", "Desktop native tool timed out; accepted/start evidence remains separate") from error
    finally:
        client.close()
