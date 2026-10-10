"""Submit one exact role-owned delivery update to an existing SLK.Run."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from temporalio.client import Client

from .contracts import DeliveryRequest, NativeStartAck, PreStartRejection
from .inspector import inspect_pair
from .workflows import RunSlkWorkflow


IDENTITY_FIELDS = {
    "schema_version", "run_id", "address", "task_queue", "start_workflow_id",
    "start_run_id", "run_workflow_id", "run_run_id", "startup_fingerprint",
}
RESULT_FIELDS = {
    "schema_version", "status", "operation", "run_id", "operation_id", "message_id",
}
RPC_TIMEOUT_SECONDS = 30.0


def _load_hashed(path: Path, expected_sha256: str, label: str) -> dict[str, Any]:
    if not path.is_absolute() or not path.is_file() or path.stat().st_size > 131072:
        raise ValueError(f"{label} is unavailable")
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise ValueError(f"{label} SHA-256 changed")
    try:
        value = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} is invalid") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return value


def _identity(value: Mapping[str, Any]) -> dict[str, str]:
    if set(value) != IDENTITY_FIELDS or value.get("schema_version") != "slk.temporal-workflow-identity/v1":
        raise ValueError("workflow identity is not closed")
    if not all(isinstance(value.get(field), str) and value[field].strip() == value[field]
               for field in IDENTITY_FIELDS - {"schema_version"}):
        raise ValueError("workflow identity contains an invalid value")
    fingerprint = str(value["startup_fingerprint"])
    if len(fingerprint) != 64 or any(character not in "0123456789abcdef" for character in fingerprint):
        raise ValueError("workflow identity fingerprint is invalid")
    return dict(value)  # type: ignore[return-value]


async def _submit_once(*, operation: str, identity: Mapping[str, str], request: Mapping[str, Any]) -> dict[str, Any]:
    if operation == "close-run":
        arguments = {field: identity[field] for field in IDENTITY_FIELDS - {"schema_version"}}
        description = await inspect_pair(**arguments, diagnostic=True)
        client = await Client.connect(identity["address"])
        handle = client.get_workflow_handle(identity["run_workflow_id"], run_id=identity["run_run_id"])
        status = await handle.query(RunSlkWorkflow.status)
        if status.get("phase") != "TERMINAL":
            if any(row["status"] != "RUNNING" for row in description["executions"].values()):
                raise ValueError("nonterminal Run has a closed native pair; diagnose before cleanup")
            await handle.execute_update(RunSlkWorkflow.close_run, request["event_id"])
        elif status.get("terminal_reason") != request["event_id"]:
            raise ValueError("pair terminal reason differs from this exact close event")
        # Only this pair: Start naturally awaits its child. Never cancel the
        # shared worker/service, nor another workflow with a similar name.
        await handle.result()
        parent = client.get_workflow_handle(identity["start_workflow_id"], run_id=identity["start_run_id"])
        await parent.result()
        final = await inspect_pair(**arguments, diagnostic=True)
        if any(row["status"] != "COMPLETED" or not row["close_time"] for row in final["executions"].values()):
            raise ValueError("exact native pair has not completed")
        return {"schema_version": "slk.temporal-close-result/v1", "status": "PAIR_CLOSED",
                "run_id": identity["run_id"], "event_id": request["event_id"]}
    await inspect_pair(**{field: identity[field] for field in IDENTITY_FIELDS - {"schema_version"}})
    client = await Client.connect(identity["address"])
    handle = client.get_workflow_handle(identity["run_workflow_id"], run_id=identity["run_run_id"])
    if operation == "set-run-pause":
        status = await handle.execute_update(RunSlkWorkflow.set_run_pause, dict(request))
        return {"schema_version": "slk.temporal-lifecycle-update-result/v1", "status": status,
                "run_id": identity["run_id"], "event_id": request["event_id"]}
    if operation == "request-delivery":
        parsed = DeliveryRequest.from_dict(request)
        if parsed.run_id != identity["run_id"]:
            raise ValueError("delivery request changed the existing Run")
        status = await handle.execute_update(RunSlkWorkflow.request_delivery, parsed.to_dict())
        operation_name = "request_delivery"
        message_id, operation_id = parsed.message_id, parsed.operation_id
    elif operation == "native-started":
        parsed_ack = NativeStartAck.from_dict(request)
        status = await handle.execute_update(RunSlkWorkflow.native_started, parsed_ack.to_dict())
        operation_name = "native_started"
        message_id, operation_id = parsed_ack.message_id, parsed_ack.operation_id
    elif operation == "abandon-pre-start-rejection":
        parsed_rejection = PreStartRejection.from_dict(request)
        if parsed_rejection.run_id != identity["run_id"]:
            raise ValueError("pre-start rejection changed the existing Run")
        status = await handle.execute_update(
            RunSlkWorkflow.abandon_pre_start_rejection, parsed_rejection.to_dict()
        )
        operation_name = "abandon_pre_start_rejection"
        message_id = parsed_rejection.message_id
        operation_id = parsed_rejection.operation_id
    else:
        raise ValueError("unsupported Temporal delivery operation")
    return {
        "schema_version": "slk.temporal-delivery-update-result/v1",
        "status": str(status),
        "operation": operation_name,
        "run_id": identity["run_id"],
        "operation_id": operation_id,
        "message_id": message_id,
    }


async def _submit(*, operation: str, identity: Mapping[str, str], request: Mapping[str, Any]) -> dict[str, Any]:
    try:
        return await asyncio.wait_for(
            _submit_once(operation=operation, identity=identity, request=request),
            timeout=RPC_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError as exc:
        raise TimeoutError("Temporal delivery update exceeded its RPC deadline") from exc


def submit(*, operation: str, identity: Mapping[str, str], request: Mapping[str, Any]) -> dict[str, Any]:
    return asyncio.run(_submit(operation=operation, identity=identity, request=request))


def run_update(*, operation: str, identity_path: Path, identity_sha256: str,
               request_path: Path, request_sha256: str) -> dict[str, Any]:
    identity = _identity(_load_hashed(identity_path, identity_sha256, "identity"))
    request = _load_hashed(request_path, request_sha256, "request")
    if operation == "close-run":
        if set(request) != {"run_id", "event_id"} or request.get("run_id") != identity["run_id"]:
            raise ValueError("close request changed the exact existing Run")
        result = submit(operation=operation, identity=identity, request=request)
        if result != {"schema_version": "slk.temporal-close-result/v1", "status": "PAIR_CLOSED",
                      "run_id": identity["run_id"], "event_id": request["event_id"]}:
            raise ValueError("Temporal close result identity is invalid")
        return dict(result)
    if operation == "set-run-pause":
        fields = {"run_id", "supervisor_role_instance_id", "pause_id", "event_id", "phase"}
        if "confirmed_at" in request: fields.add("confirmed_at")
        if (set(request) != fields or request.get("run_id") != identity["run_id"]
            or request.get("phase") not in {"REQUESTED", "PAUSED", "RESUMED"}
            or ("confirmed_at" in request and request["phase"] != "PAUSED")):
            raise ValueError("lifecycle request changed the existing Run")
        result = submit(operation=operation, identity=identity, request=request)
        if result != {"schema_version": "slk.temporal-lifecycle-update-result/v1", "status": request["phase"],
                      "run_id": identity["run_id"], "event_id": request["event_id"]}:
            raise ValueError("Temporal lifecycle result identity is invalid")
        return dict(result)
    if operation == "request-delivery":
        parsed = DeliveryRequest.from_dict(request)
        expected_operation, allowed = "request_delivery", {
            "DELIVERY_REQUESTED", "RECOVERY_REQUIRED", "BLOCKED", "DELIVERY_ACKNOWLEDGED",
        }
        run_id, operation_id, message_id = parsed.run_id, parsed.operation_id, parsed.message_id
    elif operation == "native-started":
        parsed_ack = NativeStartAck.from_dict(request)
        expected_operation, allowed = "native_started", {"DELIVERY_ACKNOWLEDGED"}
        run_id, operation_id, message_id = identity["run_id"], parsed_ack.operation_id, parsed_ack.message_id
    elif operation == "abandon-pre-start-rejection":
        parsed_rejection = PreStartRejection.from_dict(request)
        expected_operation = "abandon_pre_start_rejection"
        allowed = {"PRE_START_REJECTION_ABANDONED"}
        run_id = parsed_rejection.run_id
        operation_id = parsed_rejection.operation_id
        message_id = parsed_rejection.message_id
    else:
        raise ValueError("unsupported Temporal delivery operation")
    if run_id != identity["run_id"]:
        raise ValueError("request identity changed the existing Run")
    result = submit(operation=operation, identity=identity, request=request)
    if (not isinstance(result, Mapping) or set(result) != RESULT_FIELDS
        or result.get("schema_version") != "slk.temporal-delivery-update-result/v1"
        or result.get("status") not in allowed or result.get("operation") != expected_operation
        or result.get("run_id") != run_id or result.get("operation_id") != operation_id
        or result.get("message_id") != message_id):
        raise ValueError("Temporal update result identity is invalid")
    return dict(result)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "operation",
        choices=("request-delivery", "native-started", "abandon-pre-start-rejection", "set-run-pause", "close-run"),
    )
    parser.add_argument("--identity", required=True, type=Path)
    parser.add_argument("--identity-sha256", required=True)
    parser.add_argument("--request", required=True, type=Path)
    parser.add_argument("--request-sha256", required=True)
    args = parser.parse_args()
    result = run_update(operation=args.operation, identity_path=args.identity.resolve(),
                        identity_sha256=args.identity_sha256,
                        request_path=args.request.resolve(), request_sha256=args.request_sha256)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
