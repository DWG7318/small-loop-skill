from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Iterable

import yaml


HEX64 = re.compile(r"^[0-9a-fA-F]{64}$")
EVENT_TYPES = {"ACK", "PROGRESS", "BLOCKED", "FINAL"}
CONTROL_STATES = {
    "OFFLINE_WAITING_WORKER_SIGNAL",
    "ACTIVE_WORKER_ACKNOWLEDGED",
    "BLOCKED_UNREAD",
    "COMPLETED_UNREAD",
    "BLOCKED_INGESTED",
    "FINAL_INGESTED",
    "CONTROL_DISCONNECTED",
}
TERMINAL_TYPES = {"BLOCKED", "FINAL"}


def fail(code: str, detail: str) -> None:
    raise ValueError(f"{code}: {detail}")


def require_mapping(value: object, code: str) -> dict:
    if not isinstance(value, dict):
        fail(code, "expected mapping")
    return value


def require_nonempty(mapping: dict, field: str, code: str) -> object:
    value = mapping.get(field)
    if value is None or value == "" or value == {} or value == []:
        fail(code, field)
    return value


def load(path: Path) -> dict:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        fail("SLK_SIGNAL_READ", str(exc))
    try:
        value = json.loads(text) if path.suffix.lower() == ".json" else yaml.safe_load(text)
    except (json.JSONDecodeError, yaml.YAMLError) as exc:
        fail("SLK_SIGNAL_PARSE", str(exc))
    return require_mapping(value, "SLK_SIGNAL_ROOT")


def validate_binding(dispatch: dict, event: dict) -> None:
    for field in (
        "run_id",
        "dispatch_id",
        "worker_conversation_id",
        "go_id",
        "cell_id",
        "round_id",
    ):
        if event.get(field) != dispatch.get(field):
            fail("SLK_SIGNAL_BINDING_MISMATCH", field)


def validate_redispatch(delivery: dict) -> None:
    count = delivery.get("redispatch_count", 0)
    if not isinstance(count, int) or isinstance(count, bool) or count < 0:
        fail("SLK_SIGNAL_REDISPATCH_COUNT", repr(count))
    if count == 0:
        return
    if delivery.get("prior_delivery_status") != "TASK_NOT_DELIVERED_PROVEN":
        fail("SLK_SIGNAL_DUPLICATE_DISPATCH", "redispatch requires TASK_NOT_DELIVERED_PROVEN")
    require_nonempty(delivery, "redispatch_authority_ref", "SLK_SIGNAL_REDISPATCH_AUTHORITY")


def validate_stream(value: dict) -> None:
    if str(value.get("schema_version")) != "2.5":
        fail("SLK_SIGNAL_SCHEMA_VERSION", repr(value.get("schema_version")))

    dispatch = require_mapping(value.get("dispatch"), "SLK_SIGNAL_DISPATCH")
    for field in (
        "run_id",
        "dispatch_id",
        "worker_conversation_id",
        "go_id",
        "cell_id",
        "round_id",
        "task_ref",
        "created_at",
    ):
        require_nonempty(dispatch, field, "SLK_SIGNAL_DISPATCH_FIELD")

    delivery = require_mapping(value.get("delivery"), "SLK_SIGNAL_DELIVERY")
    if delivery.get("status") not in {"DELIVERED", "TASK_NOT_DELIVERED_PROVEN"}:
        fail("SLK_SIGNAL_DELIVERY_STATUS", repr(delivery.get("status")))
    validate_redispatch(delivery)

    state = value.get("control_state")
    if state not in CONTROL_STATES:
        fail("SLK_SIGNAL_CONTROL_STATE", repr(state))

    events = value.get("events")
    if not isinstance(events, list):
        fail("SLK_SIGNAL_EVENTS", "expected list")
    if not events:
        if state not in {"OFFLINE_WAITING_WORKER_SIGNAL", "CONTROL_DISCONNECTED"}:
            fail("SLK_SIGNAL_EMPTY_STATE", str(state))
        return

    seen_ids: set[str] = set()
    seen_hashes: set[str] = set()
    terminal: dict | None = None
    ack_count = 0
    for index, raw_event in enumerate(events, start=1):
        event = require_mapping(raw_event, "SLK_SIGNAL_EVENT")
        validate_binding(dispatch, event)
        if event.get("sequence") != index:
            fail("SLK_SIGNAL_SEQUENCE", f"expected {index}, got {event.get('sequence')!r}")
        event_type = event.get("event_type")
        if event_type not in EVENT_TYPES:
            fail("SLK_SIGNAL_EVENT_TYPE", repr(event_type))
        if terminal is not None:
            fail("SLK_SIGNAL_AFTER_TERMINAL", str(event_type))

        signal_id = str(require_nonempty(event, "signal_id", "SLK_SIGNAL_ID"))
        signal_sha = str(require_nonempty(event, "signal_sha256", "SLK_SIGNAL_HASH"))
        if not HEX64.fullmatch(signal_sha):
            fail("SLK_SIGNAL_HASH", signal_sha)
        if signal_id in seen_ids or signal_sha.lower() in seen_hashes:
            fail("SLK_SIGNAL_DUPLICATE_EVENT", signal_id)
        seen_ids.add(signal_id)
        seen_hashes.add(signal_sha.lower())
        require_nonempty(event, "issued_at", "SLK_SIGNAL_ISSUED_AT")

        if event_type == "ACK":
            ack_count += 1
            if index != 1 or event.get("delivery_status") != "RECEIVED":
                fail("SLK_SIGNAL_ACK", "ACK must be first and RECEIVED")
        elif ack_count != 1:
            fail("SLK_SIGNAL_ACK_REQUIRED", str(event_type))

        if event_type == "BLOCKED":
            require_nonempty(event, "required_route", "SLK_SIGNAL_BLOCKED_ROUTE")
            terminal = event
        elif event_type == "FINAL":
            candidate_state = event.get("candidate_state")
            if candidate_state not in {"IMMUTABLE_CANDIDATE", "NO_CANDIDATE"}:
                fail("SLK_SIGNAL_CANDIDATE_STATE", repr(candidate_state))
            if candidate_state == "IMMUTABLE_CANDIDATE":
                require_nonempty(event, "candidate_ref", "SLK_SIGNAL_CANDIDATE_REF")
            else:
                require_nonempty(event, "required_route", "SLK_SIGNAL_NO_CANDIDATE_ROUTE")
            terminal = event

    if ack_count != 1:
        fail("SLK_SIGNAL_ACK_COUNT", str(ack_count))

    ingestion = require_mapping(value.get("ingestion"), "SLK_SIGNAL_INGESTION")
    ingestion_status = ingestion.get("status")
    if terminal is None:
        if state not in {"ACTIVE_WORKER_ACKNOWLEDGED", "CONTROL_DISCONNECTED"}:
            fail("SLK_SIGNAL_NONTERMINAL_STATE", str(state))
        if ingestion_status != "PENDING":
            fail("SLK_SIGNAL_EARLY_INGESTION", repr(ingestion_status))
        return

    terminal_type = terminal["event_type"]
    unread_state = "BLOCKED_UNREAD" if terminal_type == "BLOCKED" else "COMPLETED_UNREAD"
    ingested_state = "BLOCKED_INGESTED" if terminal_type == "BLOCKED" else "FINAL_INGESTED"
    if state == unread_state:
        if ingestion_status != "PENDING":
            fail("SLK_SIGNAL_UNREAD_INGESTION", repr(ingestion_status))
    elif state == ingested_state:
        if ingestion_status != "INGESTED":
            fail("SLK_SIGNAL_INGESTION_STATUS", repr(ingestion_status))
        if ingestion.get("terminal_signal_id") != terminal.get("signal_id"):
            fail("SLK_SIGNAL_INGESTION_ID", repr(ingestion.get("terminal_signal_id")))
        if str(ingestion.get("terminal_signal_sha256", "")).lower() != str(terminal.get("signal_sha256")).lower():
            fail("SLK_SIGNAL_INGESTION_HASH", repr(ingestion.get("terminal_signal_sha256")))
        for field in ("ingested_at", "resulting_route", "state_sync_receipt_ref"):
            require_nonempty(ingestion, field, "SLK_SIGNAL_INGESTION_FIELD")
    elif state != "CONTROL_DISCONNECTED":
        fail("SLK_SIGNAL_TERMINAL_STATE", str(state))


def main(argv: Iterable[str]) -> int:
    args = list(argv)
    if len(args) != 1:
        print("FAIL SLK_SIGNAL_USAGE: validate_worker_signal_stream.py <stream.yaml|json>", file=sys.stderr)
        return 2
    try:
        validate_stream(load(Path(args[0])))
    except ValueError as exc:
        print(f"FAIL {exc}", file=sys.stderr)
        return 1
    print("PASS: SLK Worker signal stream is bound, ordered, terminal-safe, and ingestion-consistent.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
