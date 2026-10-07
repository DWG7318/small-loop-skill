"""Abandon one hash-bound delivery proven rejected before any native start."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Callable, Mapping

from . import worker_completion as wc
from .contracts import DeliveryResult, Endpoint, Envelope, canonical_json_sha256
from .role_host import RoleHost


REQUEST_FIELDS = {
    "schema_version", "role_host_binding_path", "role_host_binding_sha256",
    "source_attempt_path", "temporal_request_path", "temporal_request_sha256",
    "expected_runtime_revision", "expected_plan_revision", "expected_token_sequence",
    "expected_supervisor_role_instance_id", "result_path",
}
DELIVERY_FIELDS = {
    "operation_id", "run_id", "cell_id", "attempt", "message_id",
    "sender_role_instance_id", "receiver_role_instance_id", "payload_sha256",
    "source_runtime_revision",
}
FORBIDDEN_NATIVE_NAMES = {
    "started.json", "native-activity.json", "completed.json", "checker-result.json",
    "ocrv-preflight.json", "ocrv-request.json", "ocrv-result.json",
    "ocrv-review-progress.json", "native.stdout.txt", "native.stderr.txt",
}
SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} is unreadable") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return value


def _hashed_path(value: object, digest: object, label: str) -> Path:
    path = Path(str(value))
    if (
        not path.is_absolute() or not path.is_file() or not isinstance(digest, str)
        or not SHA256.fullmatch(digest) or _sha256(path) != digest
    ):
        raise ValueError(f"{label} hash binding is invalid")
    return path.resolve()


def _is_within(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _validate_legacy_envelope(raw: Mapping[str, Any]) -> None:
    if set(raw) != Envelope.FIELDS:
        raise ValueError("legacy envelope field set changed")
    payload = raw.get("payload")
    if (
        raw.get("schema_version") != "slk.transport-envelope/v1"
        or raw.get("payload_type") != "CELL_DISPATCH"
        or raw.get("sender_role") != "supervisor"
        or raw.get("receiver_role") != "checker"
        or not isinstance(payload, Mapping)
        or canonical_json_sha256(payload) != raw.get("payload_sha256")
    ):
        raise ValueError("source is not the exact legacy CELL_DISPATCH rejection")


def execute_pre_start_rejection(
    request_path: Path | str,
    *,
    request_sha256: str,
    authenticate: Callable[[RoleHost], Mapping[str, Any]] | None = None,
    load_projection: Callable[[RoleHost], Mapping[str, Any]] | None = None,
    run_temporal: Callable[[list[str], list[str]], Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    request_path = _hashed_path(request_path, request_sha256, "abandonment request")
    request = _read(request_path, "abandonment request")
    if set(request) != REQUEST_FIELDS or request.get("schema_version") != "slk.pre-start-rejection-abandonment/v1":
        raise ValueError("abandonment request is not closed")
    binding_path = _hashed_path(
        request["role_host_binding_path"], request["role_host_binding_sha256"], "RoleHost binding"
    )
    binding = _read(binding_path, "RoleHost binding")
    host = RoleHost(binding, str(request["role_host_binding_sha256"]))
    expected_supervisor = request["expected_supervisor_role_instance_id"]
    if host.endpoint("supervisor").get("role_instance_id") != expected_supervisor:
        raise ValueError("RoleHost does not bind the expected Supervisor")

    if authenticate is None:
        credential = wc.unprotect_dpapi_hex(host.credential_path("supervisor"))
        try:
            authority = host._authenticate("supervisor", credential)
        finally:
            credential = ""
    else:
        authority = authenticate(host)
    if (
        authority.get("status") != "authenticated"
        or authority.get("run_id") != binding["run_id"]
        or authority.get("role") != "supervisor"
        or authority.get("role_instance_id") != expected_supervisor
        or authority.get("runtime_revision") != request["expected_runtime_revision"]
    ):
        raise ValueError("current Supervisor authority is not proven")

    projection = host.projection() if load_projection is None else load_projection(host)
    summary = projection.get("summary")
    snapshot = projection.get("runtime_snapshot")
    if not isinstance(summary, Mapping) or not isinstance(snapshot, Mapping):
        raise ValueError("current central projection is incomplete")
    expected_boundary = (
        binding["run_id"], request["expected_runtime_revision"], request["expected_plan_revision"],
        request["expected_token_sequence"], expected_supervisor,
    )
    actual_boundary = (
        summary.get("run_id"), snapshot.get("runtime_revision"), snapshot.get("plan_revision"),
        snapshot.get("token_sequence"), snapshot.get("token_holder_role_instance_id"),
    )
    if actual_boundary != expected_boundary or binding.get("plan_revision") != request["expected_plan_revision"]:
        raise ValueError("current central boundary changed")

    source = Path(str(request["source_attempt_path"])).resolve()
    endpoint_path, envelope_path = source / "endpoint.json", source / "envelope.json"
    endpoint_raw = _read(endpoint_path, "source endpoint")
    endpoint = Endpoint.from_dict(endpoint_raw)
    envelope = _read(envelope_path, "source envelope")
    _validate_legacy_envelope(envelope)
    message_id = envelope.get("message_id")
    expected_source = Path(str(binding["temporal"]["attempt_root"])).resolve() / binding["run_id"] / str(message_id)
    if source != expected_source:
        raise ValueError("source attempt is outside the canonical ATTEMPT_ROOT")
    if (
        endpoint.run_id != binding["run_id"] or endpoint.role != "checker"
        or endpoint.role_instance_id != envelope.get("receiver_role_instance_id")
        or endpoint.endpoint_version != envelope.get("receiver_endpoint_version")
        or envelope.get("sender_role_instance_id") != expected_supervisor
    ):
        raise ValueError("source endpoint/envelope identity changed")
    if any(path.name in FORBIDDEN_NATIVE_NAMES for path in source.rglob("*")):
        raise ValueError("native start, activity, result, or UNKNOWN evidence forbids abandonment")

    accepted_path, failed_path = source / "accepted.json", source / "failed.json"
    accepted = _read(accepted_path, "accepted evidence")
    failure = DeliveryResult.from_dict(_read(failed_path, "failed evidence"))
    if accepted != {"status": "accepted", "run_id": binding["run_id"], "message_id": message_id}:
        raise ValueError("accepted evidence changed")
    if (
        failure.status != "failed" or failure.error_code != "OCRV_PAYLOAD_INVALID"
        or failure.run_id != binding["run_id"] or failure.message_id != message_id
        or failure.adapter != "ocrv-checker" or failure.native_identity != {}
        or failure.evidence != ("accepted.json", "endpoint.json", "envelope.json")
    ):
        raise ValueError("failure is not the exact proven OCRV pre-start parameter rejection")

    temporal_path = _hashed_path(
        request["temporal_request_path"], request["temporal_request_sha256"], "Temporal request"
    )
    handoff = source / "role-host" / "sender-handoff"
    if temporal_path.parent != handoff.resolve():
        raise ValueError("Temporal request is not the original sender handoff")
    temporal = _read(temporal_path, "Temporal request")
    if set(temporal) != DELIVERY_FIELDS:
        raise ValueError("Temporal delivery request is not closed")
    expected_delivery = {
        "run_id": binding["run_id"], "cell_id": envelope.get("cell_id"),
        "message_id": message_id, "sender_role_instance_id": expected_supervisor,
        "receiver_role_instance_id": endpoint.role_instance_id,
        "payload_sha256": envelope.get("payload_sha256"),
        "source_runtime_revision": request["expected_runtime_revision"],
    }
    if any(temporal.get(key) != value for key, value in expected_delivery.items()):
        raise ValueError("Temporal request does not match the original attempt and central boundary")
    if (
        _read(handoff / "endpoint.json", "sender handoff endpoint") != endpoint_raw
        or _read(handoff / "envelope.json", "sender handoff envelope") != envelope
    ):
        raise ValueError("sender handoff copy differs from the original attempt")
    requested_result_path = temporal_path.with_name(
        temporal_path.stem + ".delivery-requested.result.json"
    )
    requested_result = _read(requested_result_path, "Temporal delivery-requested result")
    if requested_result != {
        "schema_version": "slk.temporal-delivery-update-result/v1",
        "status": "DELIVERY_REQUESTED", "operation": "request_delivery",
        "run_id": binding["run_id"], "operation_id": temporal.get("operation_id"),
        "message_id": message_id,
    }:
        raise ValueError("original Temporal operation is not exactly DELIVERY_REQUESTED")

    result_path = Path(str(request["result_path"])).resolve()
    if not result_path.is_absolute() or _is_within(result_path, source):
        raise ValueError("abandonment evidence must not mutate the original attempt")
    result_path.parent.mkdir(parents=True, exist_ok=True)
    update = {
        **temporal,
        "supervisor_role_instance_id": expected_supervisor,
        "central_plan_revision": request["expected_plan_revision"],
        "central_token_sequence": request["expected_token_sequence"],
        "central_token_holder_role_instance_id": expected_supervisor,
        "delivery_request_sha256": _sha256(temporal_path),
        "endpoint_sha256": _sha256(endpoint_path),
        "envelope_sha256": _sha256(envelope_path),
        "accepted_sha256": _sha256(accepted_path),
        "failed_sha256": _sha256(failed_path),
        "failure_code": "OCRV_PAYLOAD_INVALID",
    }
    update_path = wc._write_or_reuse_stable_request(
        result_path.parent / f"pre-start-rejection-{temporal['operation_id']}.json", update
    )
    arguments = [
        "abandon-pre-start-rejection",
        "--identity", binding["temporal"]["workflow_identity_path"],
        "--identity-sha256", binding["temporal"]["workflow_identity_sha256"],
        "--request", str(update_path), "--request-sha256", _sha256(update_path),
    ]
    if run_temporal is None:
        result = wc._run_json_command(binding["temporal"]["client_command"], arguments, credential=None)
    else:
        result = run_temporal(list(binding["temporal"]["client_command"]), arguments)
    expected_result = {
        "schema_version": "slk.temporal-delivery-update-result/v1",
        "status": "PRE_START_REJECTION_ABANDONED",
        "operation": "abandon_pre_start_rejection", "run_id": binding["run_id"],
        "operation_id": temporal["operation_id"], "message_id": message_id,
    }
    core = {key: value for key, value in result.items() if key != "_slk_command"}
    if core != expected_result:
        raise ValueError("Temporal abandonment result changed identity or status")
    wc._write_or_reuse_stable_request(result_path, core)
    return core
