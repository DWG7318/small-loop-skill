"""Built-in, file-bound Temporal adapter for ordinary SLK 4.4.2 Runs.

One shared worker may serve many Runs.  Each Run has one closed JSON file named
``<run_id>.json`` under the configured root.  Activities use only existing SLK
state/transport commands; this module is not another scheduler or state store.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping
from uuid import UUID

from .contracts import DeliveryRequest, StartSlkRequest


CONFIG_FIELDS = {
    "schema_version", "method_version", "run_id", "transport_command",
    "query_command", "state_config_path", "admission_kind", "admission_path",
    "attempt_root", "notification_attempt_root", "supervisor_endpoint_path",
    "role_host_binding", "overwatcher_activity",
}
BOOTSTRAP_FIELDS = {
    "schema_version", "method_version", "run_id", "query_command", "state_config_path",
}
HOST_FIELDS = {"path", "sha256"}
OW_FIELDS_V1 = {
    "endpoint_ref", "role_instance_id", "started_path", "completed_path", "failed_path",
}
OW_FIELDS_V2 = OW_FIELDS_V1 | {"attestation_path", "attestation_sha256"}
OW_ATTESTATION_FIELDS = {
    "schema_version", "method_version", "attestation_id", "run_id",
    "role_instance_id", "endpoint_ref", "thread_id", "host_id", "cwd",
    "turn_id", "platform_input_item_id", "platform_input_sha256",
    "request_sha256", "plugin_sha256", "observed_at", "thread_status",
    "turn_status", "native_task_id", "started_sha256",
}
SHA256 = re.compile(r"^[0-9a-f]{64}$")
IDENTIFIER = re.compile(r"^[A-Za-z0-9_.-]{1,128}$")
_CONFIG_ROOT: Path | None = None


class CommandFailure(RuntimeError):
    """Keep real process evidence; a failed tool is never a health receipt."""

    def __init__(self, reason: str, completed: Any) -> None:
        super().__init__(reason)
        self.stdout, self.stderr = completed.stdout or b"", completed.stderr or b""
        self.evidence = {"reason": reason, "responsibility": "STANDARD_ADAPTER_COMMAND",
                         "exit_code": completed.returncode}
        for name, raw in (("stdout", self.stdout), ("stderr", self.stderr)):
            self.evidence.update({name: raw[:16384].decode("utf-8", errors="replace"),
                name + "_bytes": len(raw), name + "_sha256": hashlib.sha256(raw).hexdigest(),
                name + "_truncated": len(raw) > 16384})


def configure(root: Path | str) -> None:
    global _CONFIG_ROOT
    selected = Path(root).resolve()
    if not selected.is_dir():
        raise ValueError("standard adapter config root is unavailable")
    _CONFIG_ROOT = selected


def _object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} is unreadable") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return value


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _validate_ow_attestation(
    path: Path,
    *,
    expected_sha256: str,
    run_id: str,
    role_instance_id: str,
    endpoint_ref: str,
    started_path: Path,
) -> None:
    if not SHA256.fullmatch(expected_sha256) or _sha256(path) != expected_sha256:
        raise ValueError("Overwatcher attestation hash changed")
    value = _object(path, "Overwatcher Desktop attestation")
    if (set(value) != OW_ATTESTATION_FIELDS
        or value.get("schema_version") != "slk.desktop-overwatcher-attestation/v1"
        or value.get("method_version") != "4.4.2"):
        raise ValueError("Overwatcher attestation is not closed")
    for field in OW_ATTESTATION_FIELDS - {"schema_version", "method_version"}:
        if not isinstance(value.get(field), str) or not value[field] or value[field] != value[field].strip():
            raise ValueError(f"Overwatcher attestation {field} is invalid")
    try:
        UUID(value["attestation_id"])
    except ValueError as exc:
        raise ValueError("Overwatcher attestation identity is invalid") from exc
    for field in ("platform_input_sha256", "request_sha256", "plugin_sha256", "started_sha256"):
        if not SHA256.fullmatch(value[field]):
            raise ValueError(f"Overwatcher attestation {field} is invalid")
    if (value["run_id"] != run_id or value["role_instance_id"] != role_instance_id
        or value["endpoint_ref"] != endpoint_ref
        or value["started_sha256"] != _sha256(started_path)
        or value["thread_status"] != "active"
        or value["turn_status"] not in {"active", "inProgress"}
        or value["native_task_id"] != (
            f"{value['thread_id']}:{value['turn_id']}:{value['platform_input_item_id']}"
        )
        or not Path(value["cwd"]).is_absolute() or not Path(value["cwd"]).is_dir()):
        raise ValueError("Overwatcher attestation does not match the frozen binding")


def _command(value: object, label: str) -> list[str]:
    if (not isinstance(value, list) or not value
        or not all(isinstance(item, str) and item.strip() == item and item for item in value)):
        raise ValueError(f"{label} is invalid")
    executable = Path(value[0])
    if not executable.is_absolute() or not executable.is_file():
        raise ValueError(f"{label} executable is unavailable")
    return list(value)


def _existing_path(value: object, label: str, *, directory: bool = False) -> Path:
    path = Path(str(value))
    valid = path.is_absolute() and (path.is_dir() if directory else path.is_file())
    if not valid:
        raise ValueError(f"{label} is unavailable")
    return path.resolve()


def _optional_path(value: object, label: str) -> Path | None:
    if value is None:
        return None
    return _existing_path(value, label)


def _load_config(run_id: str) -> dict[str, Any]:
    if _CONFIG_ROOT is None or not IDENTIFIER.fullmatch(run_id):
        raise ValueError("standard adapter is not configured for a canonical Run")
    path = _CONFIG_ROOT / f"{run_id}.json"
    value = _object(path, "standard adapter Run config")
    schema_version = value.get("schema_version")
    if (set(value) != CONFIG_FIELDS or schema_version not in {
            "slk.temporal-standard-adapter/v1", "slk.temporal-standard-adapter/v2"}
        or value.get("method_version") != "4.4.2" or value.get("run_id") != run_id):
        raise ValueError("standard adapter Run config is not closed")
    value["transport_command"] = _command(value["transport_command"], "transport command")
    value["query_command"] = _command(value["query_command"], "query command")
    if value["admission_kind"] not in {"PRODUCT", "ISOLATED_CONFORMANCE_SAMPLE"}:
        raise ValueError("admission kind is invalid")
    for field in ("state_config_path", "admission_path", "supervisor_endpoint_path"):
        value[field] = str(_existing_path(value[field], field))
    for field in ("attempt_root", "notification_attempt_root"):
        value[field] = str(_existing_path(value[field], field, directory=True))
    host = value.get("role_host_binding")
    if not isinstance(host, Mapping) or set(host) != HOST_FIELDS or not SHA256.fullmatch(str(host.get("sha256", ""))):
        raise ValueError("role host binding reference is invalid")
    host_path = _existing_path(host["path"], "role host binding")
    if _sha256(host_path) != host["sha256"]:
        raise ValueError("role host binding hash changed")
    value["role_host_binding"] = {"path": str(host_path), "sha256": host["sha256"]}
    ow = value.get("overwatcher_activity")
    expected_ow_fields = OW_FIELDS_V2 if schema_version == "slk.temporal-standard-adapter/v2" else OW_FIELDS_V1
    if (not isinstance(ow, Mapping) or set(ow) != expected_ow_fields
        or not all(isinstance(ow[field], str) and IDENTIFIER.fullmatch(ow[field])
                   for field in ("endpoint_ref", "role_instance_id"))):
        raise ValueError("Overwatcher activity binding is invalid")
    normalized_ow = {
        **dict(ow),
        "started_path": str(_existing_path(ow["started_path"], "Overwatcher native start")),
        "completed_path": str(path) if (path := _optional_path(ow["completed_path"], "Overwatcher completed evidence")) else None,
        "failed_path": str(path) if (path := _optional_path(ow["failed_path"], "Overwatcher failed evidence")) else None,
    }
    if schema_version == "slk.temporal-standard-adapter/v2":
        attestation_path = _existing_path(ow["attestation_path"], "Overwatcher Desktop attestation")
        _validate_ow_attestation(
            attestation_path,
            expected_sha256=str(ow["attestation_sha256"]),
            run_id=run_id,
            role_instance_id=str(ow["role_instance_id"]),
            endpoint_ref=str(ow["endpoint_ref"]),
            started_path=Path(normalized_ow["started_path"]),
        )
        normalized_ow["attestation_path"] = str(attestation_path)
    value["overwatcher_activity"] = normalized_ow
    return value


def _load_bootstrap_config(run_id: str) -> dict[str, Any]:
    if _CONFIG_ROOT is None or not IDENTIFIER.fullmatch(run_id):
        raise ValueError("standard adapter is not configured for a canonical Run")
    value = _object(_CONFIG_ROOT / f"{run_id}.bootstrap.json", "standard adapter bootstrap config")
    if (set(value) != BOOTSTRAP_FIELDS
        or value.get("schema_version") != "slk.temporal-standard-bootstrap/v1"
        or value.get("method_version") != "4.4.2" or value.get("run_id") != run_id):
        raise ValueError("standard adapter bootstrap config is not closed")
    value["query_command"] = _command(value["query_command"], "query command")
    value["state_config_path"] = str(_existing_path(value["state_config_path"], "state config"))
    return value


def bootstrap_run(value: dict[str, Any]) -> dict[str, Any]:
    """Validate only the live central registry needed before creating a workflow pair."""
    request = StartSlkRequest.from_dict(value)
    config = _load_bootstrap_config(request.run_id)
    projection = _run_json(
        list(config["query_command"]), ["run", "--run-id", request.run_id],
        environment={"SLK_CONFIG_PATH": str(config["state_config_path"])},
    )
    runtime = projection.get("runtime_snapshot", {})
    roles = projection.get("roles")
    if (projection.get("summary", {}).get("run_id") != request.run_id
        or runtime.get("runtime_revision") != request.runtime_revision
        or runtime.get("method_version") != request.method_version
        or not isinstance(roles, list)):
        raise ValueError("live central Run does not match Temporal bootstrap input")
    active: dict[str, str] = {}
    for row in roles:
        if not isinstance(row, Mapping) or row.get("lifecycle") != "active":
            continue
        role, identity = str(row.get("role", "")).upper(), row.get("role_instance_id")
        if role in active or not isinstance(identity, str):
            raise ValueError("live central role registry is ambiguous")
        active[role] = identity
    expected = {item.role: item.role_instance_id for item in request.roles}
    if active != expected:
        raise ValueError("live central role registry does not match Temporal bootstrap input")
    core = {"status": "BOOTSTRAP_READY", "run_id": request.run_id,
            "runtime_revision": request.runtime_revision,
            "startup_fingerprint": request.startup_fingerprint}
    return {**core, "receipt_sha256": _receipt(core)}


def _run_json(
    command: list[str], arguments: list[str], *, environment: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    env = os.environ.copy()
    if environment:
        env.update(environment)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    creationflags = int(getattr(subprocess, "CREATE_NO_WINDOW", 0)) if os.name == "nt" else 0
    completed = subprocess.run(
        [*command, *arguments], stdin=subprocess.DEVNULL, capture_output=True, check=False,
        env=env, creationflags=creationflags,
    )
    for raw in (completed.stdout, completed.stderr):
        if not raw:
            continue
        try:
            value = json.loads(raw.decode("utf-8").strip())
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
        if isinstance(value, dict):
            if completed.returncode != 0 and value.get("status") not in {
                "REPAIR_NEEDED", "INCOMPATIBLE", "UNKNOWN", "DEAD_WITHOUT_TERMINAL",
                "COMPLETED_WITHOUT_TERMINAL", "FAILED_WITHOUT_TERMINAL",
                "LATE", "CONTINUITY_UNPROVEN",
            }:
                raise CommandFailure("standard adapter command failed", completed)
            return value
    raise CommandFailure("standard adapter command returned no closed JSON", completed)


def _receipt(value: Mapping[str, Any]) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _query(config: Mapping[str, Any]) -> dict[str, Any]:
    return _run_json(
        list(config["query_command"]), ["run", "--run-id", str(config["run_id"])],
        environment={"SLK_CONFIG_PATH": str(config["state_config_path"])},
    )


async def prepare_run(value: dict[str, Any]) -> dict[str, Any]:
    if isinstance(value, Mapping) and set(value) == {"recovery"}:
        from .recovery_client import validate_source
        return await validate_source(value["recovery"], config_root=_CONFIG_ROOT)
    if not isinstance(value, Mapping) or set(value) != {"request", "startup_fingerprint"}:
        raise ValueError("prepare_run input is not closed")
    request = StartSlkRequest.from_dict(value["request"])
    fingerprint = value["startup_fingerprint"]
    if not isinstance(fingerprint, str) or not SHA256.fullmatch(fingerprint):
        raise ValueError("startup fingerprint is invalid")
    config = _load_config(request.run_id)

    def perform() -> dict[str, Any]:
        command = ("preflight-new-run" if config["admission_kind"] == "PRODUCT"
                   else "preflight-conformance-sample")
        admission = _run_json(
            list(config["transport_command"]),
            [command, "--request", str(config["admission_path"])],
            environment={"SLK_CONFIG_PATH": str(config["state_config_path"])},
        )
        projection = _query(config)
        if (admission.get("status") != "READY" or admission.get("run_id") != request.run_id
            or projection.get("summary", {}).get("run_id") != request.run_id
            or projection.get("runtime_snapshot", {}).get("runtime_revision") != request.runtime_revision):
            raise ValueError("new Run admission or live runtime revision does not match startup")
        core = {"status": "READY", "run_id": request.run_id,
                "runtime_revision": request.runtime_revision,
                "startup_fingerprint": fingerprint}
        return {**core, "receipt_sha256": _receipt(core)}

    return await asyncio.to_thread(perform)


def _delivery_files(config: Mapping[str, Any], request: DeliveryRequest) -> tuple[Path, Path, Path]:
    attempt = Path(str(config["attempt_root"])) / request.run_id / request.message_id
    endpoint_path, envelope_path = attempt / "endpoint.json", attempt / "envelope.json"
    endpoint, envelope = _object(endpoint_path, "staged endpoint"), _object(envelope_path, "staged envelope")
    expected = {
        "run_id": request.run_id, "cell_id": request.cell_id, "message_id": request.message_id,
        "sender_role_instance_id": request.sender_role_instance_id,
        "receiver_role_instance_id": request.receiver_role_instance_id,
        "payload_sha256": request.payload_sha256,
    }
    if any(envelope.get(field) != wanted for field, wanted in expected.items()):
        raise ValueError("staged delivery changed Temporal identity")
    if endpoint.get("run_id") != request.run_id or endpoint.get("role_instance_id") != request.receiver_role_instance_id:
        raise ValueError("staged endpoint changed Temporal receiver")
    return attempt, endpoint_path, envelope_path


async def deliver_message(value: dict[str, Any]) -> dict[str, Any]:
    request = DeliveryRequest.from_dict(value)
    config = _load_config(request.run_id)

    def perform() -> dict[str, Any]:
        attempt, endpoint_path, envelope_path = _delivery_files(config, request)
        host = config["role_host_binding"]
        result = _run_json(
            list(config["transport_command"]),
            ["send", "--endpoint", str(endpoint_path), "--envelope", str(envelope_path),
             "--attempt-root", str(config["attempt_root"])],
            environment={"SLK_CONFIG_PATH": str(config["state_config_path"]),
                         "SLK_TRANSPORT_ROLE_HOST": str(host["path"]),
                         "SLK_TRANSPORT_ROLE_HOST_SHA256": str(host["sha256"])},
        )
        started = _object(attempt / "started.json", "native start")
        exact = (result.get("status") in {"started", "completed"}
                 and result.get("run_id") == request.run_id
                 and result.get("message_id") == request.message_id
                 and started.get("schema_version") == "slk.native-start/v2"
                 and started.get("status") == "STARTED"
                 and all(started.get(field) == wanted for field, wanted in {
                     "run_id": request.run_id, "cell_id": request.cell_id,
                     "message_id": request.message_id, "request_sha256": request.payload_sha256,
                 }.items()))
        core = {"status": "DELIVERED" if exact else "FAILED", "operation_id": request.operation_id}
        return {**core, "receipt_sha256": _receipt(core)}

    return await asyncio.to_thread(perform)


async def request_recovery(value: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != {"delivery", "recovery_target_role_instance_id"}:
        raise ValueError("recovery request is not closed")
    delivery = DeliveryRequest.from_dict(value["delivery"])
    if value["recovery_target_role_instance_id"] != delivery.sender_role_instance_id:
        raise ValueError("recovery target is not the original sender")
    config = _load_config(delivery.run_id)

    def perform() -> dict[str, Any]:
        attempt, endpoint_path, envelope_path = _delivery_files(config, delivery)
        try:
            result = _run_json(
                list(config["transport_command"]),
                ["inspect", "--endpoint", str(endpoint_path), "--envelope", str(envelope_path),
                 "--attempt-root", str(config["attempt_root"])],
                environment={"SLK_CONFIG_PATH": str(config["state_config_path"])},
            )
        except CommandFailure as error:
            for name, raw in (("stdout", error.stdout), ("stderr", error.stderr)):
                path = attempt / f"recovery-inspection.{name}.log"
                if path.exists() and path.read_bytes() != raw:
                    raise ValueError("recovery inspection evidence changed") from error
                path.write_bytes(raw)
                error.evidence[name + "_path"] = str(path)
            _write_once(attempt / "recovery-inspection-failure.json", error.evidence)
            raise
        # An already proven start lets the original sender finish its normal ACK.
        # Otherwise the adapter stops; Supervisor chooses any exact mechanical retry.
        status = "RECOVERY_REQUESTED" if result.get("status") == "ALREADY_STARTED" else "BLOCKED"
        if status == "RECOVERY_REQUESTED" and not (attempt / "started.json").is_file():
            status = "BLOCKED"
        core = {"status": status, "operation_id": delivery.operation_id}
        return {**core, "receipt_sha256": _receipt(core)}

    return await asyncio.to_thread(perform)


async def inspect_overwatcher(value: dict[str, Any]) -> dict[str, Any]:
    fields = {"run_id", "overwatcher_role_instance_id", "endpoint_ref", "audit_cycle"}
    if not isinstance(value, Mapping) or set(value) != fields or type(value.get("audit_cycle")) is not int:
        raise ValueError("Overwatcher audit input is not closed")
    config = _load_config(str(value["run_id"]))
    ow = config["overwatcher_activity"]
    if (value["overwatcher_role_instance_id"] != ow["role_instance_id"]
        or value["endpoint_ref"] != ow["endpoint_ref"] or value["audit_cycle"] < 1):
        raise ValueError("Overwatcher audit changed the frozen identity")

    def perform() -> dict[str, Any]:
        arguments = ["inspect-native-activity", "--started", ow["started_path"]]
        if config["schema_version"] == "slk.temporal-standard-adapter/v2":
            arguments.extend((
                "--desktop-overwatcher-attestation", ow["attestation_path"],
                "--desktop-overwatcher-attestation-sha256", ow["attestation_sha256"],
            ))
        for option, field in (("--completed", "completed_path"), ("--failed", "failed_path")):
            if ow[field] is not None:
                arguments.extend((option, ow[field]))
        observation = _run_json(list(config["transport_command"]), arguments)
        # Being online does not prove that the bound Run received its due observation cycle.
        with tempfile.TemporaryDirectory(prefix="slk-ow-audit-", dir=config["notification_attempt_root"]) as temporary:
            projection_path = Path(temporary) / "projection.json"
            _write_once(projection_path, _query(config))
            cadence = _run_json(list(config["transport_command"]), [
                "inspect-overwatcher-cadence", "--runtime-projection", str(projection_path),
                "--observed-at", datetime.now(timezone.utc).isoformat(),
            ])
        age = cadence.get("elapsed_seconds")
        current_cycle = (
            cadence.get("schema_version") == "slk.overwatcher-cadence-inspection/v1"
            and cadence.get("status") == "CURRENT" and cadence.get("run_id") == value["run_id"]
            and cadence.get("overwatcher_role_instance_id") == value["overwatcher_role_instance_id"]
            and isinstance(cadence.get("latest_cycle_id"), str) and bool(cadence["latest_cycle_id"])
            and cadence.get("cadence_seconds") == 600 and type(age) is int and 0 <= age <= 600
        )
        evidence_sha256 = _receipt({"native": observation, "cadence": cadence})
        core = {"status": "CLEAR" if current_cycle and observation.get("status") in {"ACTIVE", "IDLE", "PENDING"} else "ANOMALY",
                "run_id": value["run_id"], "overwatcher_role_instance_id": value["overwatcher_role_instance_id"],
                "audit_cycle": value["audit_cycle"], "evidence_sha256": evidence_sha256}
        return {**core, "receipt_sha256": _receipt(core)}

    return await asyncio.to_thread(perform)


async def notify_supervisor(value: dict[str, Any]) -> dict[str, Any]:
    config = _load_config(str(value.get("run_id", "")))

    def perform() -> dict[str, Any]:
        projection = _query(config)
        event_id = str(value.get("event_id", "invalid"))
        root = Path(str(config["notification_attempt_root"])) / str(config["run_id"]) / event_id
        root.mkdir(parents=True, exist_ok=True)
        projection_path = root / "runtime-projection.json"
        request_path = root / "notification-request.json"
        _write_once(projection_path, projection)
        request = {"notification": dict(value),
                   "endpoint_path": str(config["supervisor_endpoint_path"]),
                   "runtime_projection_path": str(projection_path),
                   "attempt_root": str(config["notification_attempt_root"])}
        _write_once(request_path, request)
        return _run_json(list(config["transport_command"]),
                         ["notify-supervisor", "--request", str(request_path)],
                         environment={"SLK_CONFIG_PATH": str(config["state_config_path"])})

    return await asyncio.to_thread(perform)


def _write_once(path: Path, value: Mapping[str, Any]) -> None:
    encoded = (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    if path.exists():
        if path.read_bytes() != encoded:
            raise ValueError("standard adapter immutable evidence changed")
        return
    path.write_bytes(encoded)
