"""Existing host/Temporal adapter helpers: native wake proof and independent OW exit evidence.

No scheduler or engineering writer. Requested model metadata is not execution attestation.
"""
from dataclasses import dataclass
import json
import uuid
from pathlib import Path
from typing import Any, Mapping

from .adapters.codex import CodexAdapter
from .adapters.codex_desktop import deliver_desktop
from .contracts import Endpoint, canonical_json_sha256
from .evidence import Attempt
from .native_activity import inspect_native_activity, validate_native_start
from . import worker_completion as wc


@dataclass(frozen=True)
class _NoticeIdentity:
    run_id: str
    message_id: str
    payload_sha256: str
    cell_id: str = "PREPARATION"


def notify_registered_supervisor(notice: Mapping[str, Any], endpoint_raw: Mapping[str, Any],
                                 projection: Mapping[str, Any], attempt_root: Path) -> dict[str, Any]:
    fields = {"schema_version", "run_id", "event_id", "sender_role_instance_id", "receiver_role_instance_id", "message"}
    if (set(notice) != fields or notice.get("schema_version") not in {"slk.ow-notification/v1", "slk.temporal-notification/v1"}
        or not all(isinstance(notice[k], str) and notice[k] == notice[k].strip() and notice[k] for k in fields)
        or not notice["message"].startswith("发现异常，请查验") or len(notice["message"]) > 4000
        or str(uuid.UUID(notice["event_id"])) != notice["event_id"]):
        raise ValueError("operational notice is not closed or bounded")
    endpoint = Endpoint.from_dict(endpoint_raw)
    if endpoint.role != "supervisor" or endpoint.run_id != notice["run_id"] or endpoint.state != "active" or "desktop" not in endpoint.address:
        raise ValueError("notice requires its prepared native Desktop Supervisor entry")
    CodexAdapter().validate_address(endpoint)
    roles = projection.get("roles", [])
    if not isinstance(roles, list) or not all(isinstance(r, Mapping) for r in roles):
        raise ValueError("registered role observations are malformed")
    supervisors = [r for r in roles if r.get("role") == "supervisor" and r.get("lifecycle") == "active"]
    binding = endpoint.address["desktop"]
    if (projection.get("summary", {}).get("run_id") != notice["run_id"] or len(supervisors) != 1
        or notice["receiver_role_instance_id"] != endpoint.role_instance_id
        or supervisors[0].get("role_instance_id") != endpoint.role_instance_id
        or supervisors[0].get("session_id") != endpoint.address["thread_id"]
        or supervisors[0].get("model") != binding["model"] or supervisors[0].get("reasoning") != binding["reasoning_effort"]):
        raise ValueError("notification changed the registered Supervisor identity or model binding")
    if notice["schema_version"] == "slk.ow-notification/v1":
        senders = [r for r in roles if r.get("role") == "overwatcher" and r.get("lifecycle") == "active"
                   and r.get("role_instance_id") == notice["sender_role_instance_id"]]
        if len(senders) != 1:
            raise ValueError("OW notice sender is not registered")
        if senders[0].get("agent_runtime") == "codex" and senders[0].get("session_id") != binding["caller_thread_id"]:
            raise ValueError("notice caller is not the registered native OW Session")
    elif notice["sender_role_instance_id"] != "temporal:" + notice["run_id"]:
        raise ValueError("independent Temporal source identity changed")
    root = Path(attempt_root).resolve() / notice["run_id"] / notice["event_id"]
    identity = _NoticeIdentity(notice["run_id"], notice["event_id"], canonical_json_sha256(notice))
    if (root / "notification-result.json").is_file():
        if (wc._read_object(root / "notification.json", "notice") != dict(notice)
            or wc._read_object(root / "endpoint.json", "notification endpoint") != dict(endpoint_raw)):
            raise ValueError("saved notice identity changed")
        result = wc._read_object(root / "notification-result.json", "notification result")
        start = validate_native_start(root / "started.json", adapter=endpoint.adapter, run_id=notice["run_id"],
            cell_id="PREPARATION", message_id=notice["event_id"], request_sha256=identity.payload_sha256)
        if result.get("native_start") != start or result.get("receipt_sha256") != canonical_json_sha256({k: v for k, v in result.items() if k != "receipt_sha256"}):
            raise ValueError("saved notification proof changed")
        return result
    if root.is_dir() and any(root.iterdir()):
        raise ValueError("previous operational send is uncertain; inspect it before another send")
    root.mkdir(parents=True, exist_ok=True)
    attempt = Attempt(root)
    attempt.write_json_once("notification.json", notice)
    attempt.write_json_once("endpoint.json", endpoint_raw)
    prompt = notice["message"] + "\n" + json.dumps(dict(notice), ensure_ascii=False, sort_keys=True)
    # Only exact platform delivery proves wake. The Supervisor still decides what
    # to do; this receipt never claims takeover, repair, or engineering acceptance.
    native = deliver_desktop(endpoint, identity, attempt, prompt, wait_for_completion=False)
    attempt.write_json_once("delivery-result.json", native.to_dict())
    start = validate_native_start(root / "started.json", adapter=endpoint.adapter, run_id=notice["run_id"],
        cell_id="PREPARATION", message_id=notice["event_id"], request_sha256=identity.payload_sha256)
    result = {"status": "NOTIFIED", "event_id": notice["event_id"], "supervisor_role_instance_id": endpoint.role_instance_id,
              "native_start": start}
    result["receipt_sha256"] = canonical_json_sha256(result)
    attempt.write_json_once("notification-result.json", result)
    return result


def observe_overwatcher_exit(started_path: Path, *, run_id: str, role_instance_id: str,
                             native_task_id: str, requested_by_role_instance_id: str) -> dict[str, Any] | None:
    """Called by the existing owning host's exit hook or Temporal audit, not OW."""
    start = validate_native_start(started_path, run_id=run_id)
    if start["native_task"]["id"] != native_task_id:
        raise ValueError("exit observation changed the registered native OW Session")
    event_id = wc._stable_id(str(started_path.resolve()), "ow-exit-" + wc._sha256(started_path))
    path = started_path.parent / "exit-hook" / (event_id + ".json")
    if path.is_file():
        saved = wc._read_object(path, "independent exit evidence")
        if (saved.get("start_sha256") != wc._sha256(started_path) or saved.get("run_id") != run_id
            or saved.get("role_instance_id") != role_instance_id or saved.get("native_task_id") != native_task_id
            or saved.get("requested_by_role_instance_id") != requested_by_role_instance_id):
            raise ValueError("preserved exit observation changed identity")
        digest = canonical_json_sha256(saved)
        return {"event_id": event_id, "run_id": run_id, "overwatcher_role_instance_id": role_instance_id,
                "requested_by_role_instance_id": requested_by_role_instance_id, "evidence_sha256": digest}
    observation = inspect_native_activity(started_path)
    if observation["status"] in {"ACTIVE", "PENDING", "IDLE"}:
        return None
    if observation["status"] not in {"DEAD_WITHOUT_TERMINAL", "COMPLETED_WITHOUT_TERMINAL", "FAILED_WITHOUT_TERMINAL"}:
        raise ValueError("OW exit is unproved; report observation failure, not a confirmed stop")
    record = {"start_sha256": wc._sha256(started_path), "observation": observation, "run_id": run_id,
        "role_instance_id": role_instance_id, "native_task_id": native_task_id,
        "requested_by_role_instance_id": requested_by_role_instance_id}
    path.parent.mkdir(parents=True, exist_ok=True)
    wc._write_or_reuse_stable_request(path, record)
    digest = canonical_json_sha256(record)
    return {"event_id": event_id, "run_id": run_id,
        "overwatcher_role_instance_id": role_instance_id, "requested_by_role_instance_id": requested_by_role_instance_id,
        "evidence_sha256": digest}


def notify_temporal_supervisor(value: Mapping[str, Any], endpoint_raw: Mapping[str, Any],
                               projection: Mapping[str, Any], attempt_root: Path) -> dict[str, Any]:
    """Existing slk.notify_supervisor activity adapter; never commits a TOKEN."""
    if (set(value) != {"event_id", "kind", "run_id", "responsible_role_instance_id", "source_operation_id", "threshold_seconds"}
        or not all(isinstance(value[k], str) and value[k].strip() for k in value if k != "threshold_seconds")
        or type(value["threshold_seconds"]) is not int or value["threshold_seconds"] < 0):
        raise ValueError("Temporal notice is not closed")
    notice = {"schema_version": "slk.temporal-notification/v1", "run_id": value["run_id"],
        "event_id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"slk.temporal-notification:{value['run_id']}:{value['event_id']}")),
        "sender_role_instance_id": "temporal:" + value["run_id"], "receiver_role_instance_id": endpoint_raw["role_instance_id"],
        "message": "发现异常，请查验。\n" + json.dumps(dict(value), ensure_ascii=False, sort_keys=True)}
    native = notify_registered_supervisor(notice, endpoint_raw, projection, attempt_root)
    receipt = {k: v for k, v in native.items() if k != "receipt_sha256"}
    receipt["event_id"] = value["event_id"]
    receipt["receipt_sha256"] = canonical_json_sha256(receipt)
    return receipt
