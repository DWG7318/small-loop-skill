"""Read-only, current-Codex rollout adapter for one parent-owned native child.

This private JSONL format is not a stable platform API or cryptographic proof.
Only the registered file under this host's Codex sessions root is read. No child
tool activity, host identity, engineering authority or continued life is inferred.
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

from slk_overwatch_tools.native_records import (
    CALL_ID, OverwatcherSubagentError, native_text as _text, native_object as _object,
    native_timestamp as _timestamp, native_execution as _execution, spawn_call_id as _spawn_id,
    read_codex_subagent_snapshot as _snapshot,
)

from .native_activity import (
    TASK_ACTIVITY_SCHEMA, make_native_start, sha256_file, utc_now,
    validate_native_start, validate_native_task_activity,
)


CODEX_SESSIONS_ROOT = Path.home() / ".codex" / "sessions"
REQUEST_SCHEMA = "slk.subagent-overwatcher-request/v1"
PROOF_SCHEMA = "slk.subagent-overwatcher-proof/v1"
REQUEST_FIELDS = frozenset({
    "schema_version", "method_version", "run_id", "role_instance_id", "endpoint_ref",
    "native_address", "native_execution_id", "native_source_path",
})
PROOF_FIELDS = REQUEST_FIELDS | frozenset({
    "request_sha256", "canonical_task_id", "native_task_id", "spawn_call_id",
    "spawn_call_sha256", "spawn_output_sha256", "spawn_query_timestamp", "spawn_output_timestamp",
    "sample_call_id", "sample_call_sha256", "sample_output_sha256", "sample_query_timestamp",
    "sample_output_timestamp", "agent_status", "checked_at", "started_sha256",
})
FOLLOWUP_REQUEST_FIELDS = frozenset({"spawn_call_id", "previous_native_execution_id", "pre_activation_sample_call_id"})
FOLLOWUP_PROOF_FIELDS = FOLLOWUP_REQUEST_FIELDS | frozenset(
    f"{prefix}_{suffix}" for prefix in ("activation", "previous_activation", "pre_activation_sample")
    for suffix in ("call_sha256", "output_sha256", "query_timestamp", "output_timestamp")
)
SHA256 = re.compile(r"^[0-9a-f]{64}$")
CHILD_PATH = re.compile(r"^/root(?:/[a-z0-9_]+)+$")


def _fields(value: Mapping[str, Any], *, proof: bool = False) -> frozenset[str]:
    base = PROOF_FIELDS if proof else REQUEST_FIELDS
    if "child_source_path" in value:
        base |= {"child_source_path"}
        if proof:
            base |= {"child_session_id", "child_meta_sha256", "child_link_sha256"}
    if _execution(value.get("native_execution_id"))[0] == "codex-subagent-followup":
        return base | (FOLLOWUP_PROOF_FIELDS if proof else FOLLOWUP_REQUEST_FIELDS)
    return base


def _identity(value: Mapping[str, Any]) -> None:
    if value.get("method_version") not in {"4.5.0", "4.5.1"}:
        raise OverwatcherSubagentError("subagent OW method version is unsupported")
    for field in ("run_id", "role_instance_id", "endpoint_ref"):
        _text(value.get(field), field)
    address = value.get("native_address")
    if (not isinstance(address, dict) or set(address) != {"kind", "parent", "agent_id"}
        or address.get("kind") != "supervisor_subagent"):
        raise OverwatcherSubagentError("subagent OW native address is not closed")
    parent = address.get("parent")
    if (not isinstance(parent, dict) or set(parent) != {"agent_runtime", "host_identity", "session_id"}
        or parent.get("agent_runtime") != "codex"):
        raise OverwatcherSubagentError("subagent OW parent must use this Codex adapter")
    for field in parent:
        _text(parent[field], f"parent.{field}")
    if not CHILD_PATH.fullmatch(_text(address.get("agent_id"), "agent_id")):
        raise OverwatcherSubagentError("subagent OW child must be a canonical task path")
    kind, call_id = _execution(value.get("native_execution_id"))
    if kind == "codex-subagent-followup":
        for field in ("spawn_call_id", "pre_activation_sample_call_id"):
            if not CALL_ID.fullmatch(_text(value.get(field), field)):
                raise OverwatcherSubagentError("followup native call_id is invalid")
        previous_kind, previous_id = _execution(value.get("previous_native_execution_id"))
        if previous_id == call_id or (previous_kind == "codex-subagent-spawn" and previous_id != value["spawn_call_id"]):
            raise OverwatcherSubagentError("followup previous activation does not match")
    source = Path(_text(value.get("native_source_path"), "native_source_path"))
    if not source.is_absolute():
        raise OverwatcherSubagentError("native source must be absolute")
    try:
        relative = source.resolve(strict=True).relative_to(CODEX_SESSIONS_ROOT.resolve(strict=True))
    except (OSError, ValueError) as exc:
        raise OverwatcherSubagentError("native source is outside this host's Codex sessions root") from exc
    # Current Codex layout, including the Desktop executor suffix if present.
    if (len(relative.parts) != 4 or not re.fullmatch(r"\d{4}/\d{2}/\d{2}", "/".join(relative.parts[:3]))
        or not re.fullmatch(r"rollout-\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}-"
                            + re.escape(parent["session_id"]) + r"(?:_[0-9a-f-]+)?\.jsonl", relative.name)
        or source.is_symlink() or not source.is_file()):
        raise OverwatcherSubagentError("native source is not this parent's exact Codex rollout")
    if "child_source_path" in value:
        child_source = Path(_text(value["child_source_path"], "child_source_path"))
        try:
            child_relative = child_source.resolve(strict=True).relative_to(CODEX_SESSIONS_ROOT.resolve(strict=True))
        except (OSError, ValueError) as exc:
            raise OverwatcherSubagentError("native child source is outside this host's Codex sessions root") from exc
        if (not child_source.is_absolute() or child_source.is_symlink() or not child_source.is_file()
            or len(child_relative.parts) != 4
            or not re.fullmatch(r"\d{4}/\d{2}/\d{2}", "/".join(child_relative.parts[:3]))):
            raise OverwatcherSubagentError("native child source must be one exact Codex rollout")


def _request(path: Path, digest: str) -> dict[str, Any]:
    if not isinstance(digest, str) or not SHA256.fullmatch(digest) or sha256_file(path) != digest:
        raise OverwatcherSubagentError("subagent OW request hash does not match")
    value = _object(path.read_text(encoding="utf-8-sig"))
    if set(value) != _fields(value) or value.get("schema_version") != REQUEST_SCHEMA:
        raise OverwatcherSubagentError("subagent OW request is not closed")
    _identity(value)
    return value


def _task_id(request: Mapping[str, Any]) -> str:
    return ":".join(("codex-subagent", request["native_address"]["parent"]["session_id"],
                     request["native_execution_id"].split(":", 1)[1], request["native_address"]["agent_id"]))


def _canonical_task_id(request: Mapping[str, Any]) -> str:
    return "codex-subagent-spawn-" + _spawn_id(request)


def _activation_sha256(snapshot: Mapping[str, Any]) -> str:
    return snapshot.get("activation_call_sha256", snapshot["spawn_call_sha256"])


def _activity(request: Mapping[str, Any], snapshot: Mapping[str, Any]) -> dict[str, Any]:
    sequence = snapshot["sequence"]
    return {
        "schema_version": TASK_ACTIVITY_SCHEMA, "adapter": "codex-overwatcher",
        "run_id": request["run_id"], "cell_id": "RUN-OVERWATCH",
        "message_id": request["native_execution_id"].replace(":", "-", 1),
        "native_task_id": _task_id(request), "status": snapshot["agent_status"], "sequence": sequence,
        # Re-reading does not manufacture a newer native sample.
        "observed_at": snapshot["sample_query_timestamp"],
        "last_event": {"kind": ("CODEX_SUBAGENT_CHILD_LIST_READBACK" if snapshot.get("child_sample_selected")
                                else "CODEX_SUBAGENT_LIST_READBACK"), "sequence": sequence,
                       "observed_at": snapshot["sample_output_timestamp"],
                       "detail_sha256": snapshot["sample_output_sha256"]},
        "waiting_on": "CODEX_SUBAGENT" if snapshot["agent_status"] == "RUNNING" else None,
    }


def _write_once(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError:
        if path.read_bytes() != data:
            raise OverwatcherSubagentError("subagent OW evidence conflicts with existing evidence")


def _json_bytes(value: Mapping[str, Any]) -> bytes:
    return (json.dumps(value, sort_keys=True, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")


def _proof(path: Path, digest: str, started_path: Path) -> dict[str, Any]:
    if not isinstance(digest, str) or not SHA256.fullmatch(digest) or sha256_file(path) != digest:
        raise OverwatcherSubagentError("subagent OW proof hash does not match")
    value = _object(path.read_text(encoding="utf-8-sig"))
    if set(value) != _fields(value, proof=True) or value.get("schema_version") != PROOF_SCHEMA:
        raise OverwatcherSubagentError("subagent OW proof is not closed")
    _identity(value)
    for field in _fields(value, proof=True) - _fields(value) - {"schema_version"}:
        _text(value[field], field)
        if field.endswith("_sha256") and not SHA256.fullmatch(value[field]):
            raise OverwatcherSubagentError("subagent OW proof digest is invalid")
        if field.endswith("_call_id") and not CALL_ID.fullmatch(value[field]):
            raise OverwatcherSubagentError("subagent OW proof native call_id is invalid")
        if field.endswith("_timestamp") or field == "checked_at":
            _timestamp(value[field])
    if value["agent_status"] != "RUNNING" or sha256_file(started_path) != value["started_sha256"]:
        raise OverwatcherSubagentError("subagent OW proof does not match its running native start")
    return value


def validate_subagent_overwatcher_binding(proof_path: Path, *, proof_sha256: str,
                                        started_path: Path, projection: Mapping[str, Any]) -> dict[str, Any]:
    """Rejoin one proof to current central registration, not to role names alone.

    The parent host is a registered declaration, not independently attested by
    the rollout. Original activation/status records are checked by the probe.
    """
    proof = _proof(proof_path, proof_sha256, started_path)
    if (projection.get("summary", {}).get("run_id") != proof["run_id"]
        or projection.get("summary", {}).get("slk_version") != proof["method_version"]
        or projection.get("runtime_snapshot", {}).get("method_version") != proof["method_version"]):
        raise OverwatcherSubagentError("native OW proof differs from the current Run")
    roles = projection.get("roles")
    if not isinstance(roles, list) or not all(isinstance(row, Mapping) for row in roles):
        raise OverwatcherSubagentError("native OW current role registry is unavailable")
    parent = proof["native_address"]["parent"]
    child = proof["native_address"]["agent_id"]
    for role, session in (("supervisor", parent["session_id"]), ("overwatcher", child)):
        active = [row for row in roles if row.get("role") == role and row.get("lifecycle") == "active"]
        if len(active) != 1 or active[0].get("agent_runtime") != parent["agent_runtime"] or active[0].get("session_id") != session:
            raise OverwatcherSubagentError("native OW current parent/child Session differs")
        row = active[0]
        endpoints = row.get("endpoints")
        if not isinstance(endpoints, list) or not all(isinstance(endpoint, Mapping) for endpoint in endpoints):
            raise OverwatcherSubagentError("native OW current endpoint registry is unavailable")
        endpoints = [endpoint for endpoint in endpoints if endpoint.get("state") == "active"]
        if (len(endpoints) != 1 or endpoints[0].get("host_identity") != parent["host_identity"]
            or endpoints[0].get("session_id") != session
            or endpoints[0].get("transport_adapter") != ("codex-overwatcher" if role == "overwatcher" else "codex-app-server")):
            raise OverwatcherSubagentError("native OW current parent/child endpoint differs")
        if role == "overwatcher" and (row.get("role_instance_id") != proof["role_instance_id"]
            or row.get("foreground_turn_id") != proof["native_execution_id"]):
            raise OverwatcherSubagentError("native OW proof is not the current role/execution")
    return proof


def attest_subagent_overwatcher(request_path: Path, *, request_sha256: str, evidence_root: Path) -> dict[str, Any]:
    """Save a small proof of an existing running child; never spawn or send work."""
    request = _request(request_path, request_sha256)
    root = evidence_root.resolve()
    started_path = root / "started.json"
    proof_path = root / "subagent-overwatcher-proof.json"
    snapshot = _snapshot(request)
    activity = _activity(request, snapshot)
    try:
        for timestamp in (snapshot["sample_query_timestamp"], snapshot["sample_output_timestamp"]):
            validate_native_task_activity({**activity, "observed_at": timestamp}, adapter="codex-overwatcher",
                run_id=request["run_id"], cell_id="RUN-OVERWATCH", message_id=activity["message_id"],
                native_task_id=_task_id(request))
    except ValueError as exc:
        raise OverwatcherSubagentError("native child sample is not current") from exc
    if snapshot["agent_status"] != "RUNNING":
        raise OverwatcherSubagentError("native child is not positively running")
    _write_once(root / "subagent-overwatcher-request.json", request_path.read_bytes())
    if proof_path.exists():
        existing = _proof(proof_path, sha256_file(proof_path), started_path)
        queried = subagent_overwatcher_probe(proof_path, proof_sha256=sha256_file(proof_path),
                                             started_path=started_path, start=validate_native_start(started_path))
        if existing["request_sha256"] != request_sha256 or queried.get("status") != "RUNNING":
            raise OverwatcherSubagentError("existing subagent OW proof no longer matches")
    else:
        if started_path.exists():
            start = validate_native_start(started_path, adapter="codex-overwatcher", run_id=request["run_id"],
                cell_id="RUN-OVERWATCH", message_id=activity["message_id"], request_sha256=request_sha256,
                native_request_sha256=_activation_sha256(snapshot))
            if start["native_task"] != {"kind": "codex-subagent", "id": _task_id(request), "status": "RUNNING"}:
                raise OverwatcherSubagentError("existing start has a different native child identity")
        else:
            # Legacy process columns record only this short-lived reader, never
            # the native child's process. Platform activity never probes this PID.
            start = make_native_start(adapter="codex-overwatcher", run_id=request["run_id"], cell_id="RUN-OVERWATCH",
                message_id=activity["message_id"], request_sha256=request_sha256,
                native_request_sha256=_activation_sha256(snapshot), native_task_kind="codex-subagent",
                native_task_id=_task_id(request), native_task_status="RUNNING", pid=os.getpid())
            _write_once(started_path, _json_bytes(start))
        proof = {**request, "schema_version": PROOF_SCHEMA, "request_sha256": request_sha256,
                 "canonical_task_id": _canonical_task_id(request), "native_task_id": _task_id(request),
                 **{field: snapshot[field] for field in _fields(request, proof=True) if field in snapshot},
                 "checked_at": utc_now(), "started_sha256": sha256_file(started_path)}
        _write_once(proof_path, _json_bytes(proof))
    return {"status": "ATTESTED", "run_id": request["run_id"], "role_instance_id": request["role_instance_id"],
            "endpoint_ref": request["endpoint_ref"], "started_path": str(started_path),
            "started_sha256": sha256_file(started_path), "proof_path": str(proof_path), "proof_sha256": sha256_file(proof_path)}


def subagent_overwatcher_probe(proof_path: Path, *, proof_sha256: str,
                              started_path: Path, start: Mapping[str, Any]) -> Mapping[str, Any]:
    """Re-read the exact host source; failure never falls back to a saved snapshot."""
    try:
        proof = _proof(proof_path, proof_sha256, started_path)
        request = _request(proof_path.with_name("subagent-overwatcher-request.json"), proof["request_sha256"])
        if any(proof[field] != request[field] for field in _fields(request) - {"schema_version"}):
            raise OverwatcherSubagentError("subagent OW request/proof identity drifted")
        expected = validate_native_start(started_path, adapter="codex-overwatcher", run_id=request["run_id"],
            cell_id="RUN-OVERWATCH", message_id=request["native_execution_id"].replace(":", "-", 1), request_sha256=proof["request_sha256"],
            native_request_sha256=_activation_sha256(proof))
        if (dict(start) != expected or proof["native_task_id"] != _task_id(request)
            or proof["canonical_task_id"] != _canonical_task_id(request)
            or expected["native_task"] != {"kind": "codex-subagent", "id": _task_id(request), "status": "RUNNING"}):
            raise OverwatcherSubagentError("subagent OW native start identity drifted")
        snapshot = _snapshot(request, original_sample_id=proof["sample_call_id"])
        original = snapshot["samples"].get(proof["sample_call_id"])
        fields = _fields(request, proof=True)
        if (original is None or any(snapshot[field] != proof[field] for field in fields if field.startswith(("spawn_", "activation_", "previous_activation_", "pre_activation_sample_")) and field != "pre_activation_sample_call_id")
            or any(original[field] != proof[field] for field in fields if field.startswith("sample_"))
            or original["agent_status"] != proof["agent_status"]):
            raise OverwatcherSubagentError("original native records changed after attestation")
        if "child_source_path" in request:
            linkage_fields = ("child_session_id", "child_link_sha256")
            if snapshot["agent_status"] == "RUNNING":
                linkage_fields += ("child_meta_sha256",)
            if any(snapshot[field] != proof[field] for field in linkage_fields):
                raise OverwatcherSubagentError("original native child linkage changed after attestation")
            child_sample = snapshot.get("child_sample")
            if (snapshot["agent_status"] == "RUNNING"
                and datetime.fromisoformat(child_sample["sample_query_timestamp"].replace("Z", "+00:00"))
                    > datetime.fromisoformat(snapshot["sample_query_timestamp"].replace("Z", "+00:00"))):
                snapshot = {**snapshot, **child_sample, "child_sample_selected": True}
        return _activity(request, snapshot)
    except (OSError, ValueError, TypeError, KeyError):
        return {"status": "UNKNOWN", "error": "NATIVE_QUERY_FAILED"}
