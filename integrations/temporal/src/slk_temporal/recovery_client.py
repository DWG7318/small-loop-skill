"""Official SDK same-business-Run recovery, with immutable lineage and ACK-only resume."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping

from temporalio.client import Client, WorkflowExecutionStatus
from temporalio.common import WorkflowIDConflictPolicy, WorkflowIDReusePolicy

from .checkpoint import validate_checkpoint
from .contracts import StartSlkRequest
from .delivery_client import _identity
from .inspector import inspect_pair
from .starter import _write_identity
from . import standard_adapter as adapter


FIELDS = {"schema_version", "run_id", "source_identity", "source_executions", "checkpoint",
          "histories", "source_host", "source_config", "central_projection", "decision", "evidence_root"}


def proof(path: Path) -> dict[str, str]:
    return {"path": str(path.resolve()), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def same_proof(left: object, right: object) -> bool:
    """Same absolute file and exact SHA; Windows separator spelling is not identity."""
    if any(not isinstance(row, Mapping) or set(row) != {"path", "sha256"}
           or not isinstance(row["path"], str) or not Path(row["path"]).is_absolute()
           for row in (left, right)):
        return False
    return Path(left["path"]).resolve() == Path(right["path"]).resolve() and left["sha256"] == right["sha256"]


def read_proof(value: object, label: str) -> dict:
    if not isinstance(value, Mapping) or set(value) != {"path", "sha256"}:
        raise ValueError(f"{label} proof is not closed")
    path = Path(value["path"])
    if not path.is_absolute() or not path.is_file() or not same_proof(proof(path), value):
        raise ValueError(f"{label} proof changed")
    result = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(result, dict):
        raise ValueError(f"{label} must be an object")
    return result


def validate_request(value: object) -> tuple[dict, dict, dict]:
    if (not isinstance(value, Mapping) or set(value) != FIELDS
        or value["schema_version"] != "slk.temporal-execution-recovery/v1"):
        raise ValueError("execution recovery request is not closed")
    identity = _identity(read_proof(value["source_identity"], "source identity"))
    checkpoint = validate_checkpoint(read_proof(value["checkpoint"], "checkpoint"))
    startup = StartSlkRequest.from_dict(checkpoint["startup"])
    if (value["run_id"] != startup.run_id or identity["run_id"] != startup.run_id
        or startup.method_version not in {"4.4.2", "4.4.3"} or identity["task_queue"] != startup.task_queue
        or identity["startup_fingerprint"] != startup.startup_fingerprint):
        raise ValueError("recovery changed business Run, method, queue or immutable startup")
    executions = value["source_executions"]
    if (not isinstance(executions, Mapping) or set(executions) != {"start", "run"}
        or any(not isinstance(row, Mapping) or set(row) != {"status", "close_time"}
               or row["status"] != "FAILED" or not isinstance(row["close_time"], str)
               or not row["close_time"] for row in executions.values())):
        raise ValueError("recovery requires two proven FAILED executions")
    histories = value["histories"]
    if not isinstance(histories, Mapping) or set(histories) != {"start", "run"}:
        raise ValueError("source histories are not closed")
    for name in ("start", "run"):
        read_proof(histories[name], name + " history")
    decision = value["decision"]
    if (not isinstance(decision, Mapping) or set(decision) != {"supervisor_role_instance_id", "reason", "evidence_ref"}
        or decision["supervisor_role_instance_id"] != startup.supervisor.role_instance_id
        or not all(isinstance(decision[k], str) and decision[k].strip() == decision[k]
                   and bool(decision[k]) for k in decision)):
        raise ValueError("recovery requires the registered Supervisor's explicit disposition")
    root = Path(value["evidence_root"])
    if not root.is_absolute():
        raise ValueError("recovery evidence root must be absolute")
    host = read_proof(value["source_host"], "source host")
    config = read_proof(value["source_config"], "source config")
    if (host.get("schema_version") != "slk.role-host/v2" or host.get("run_id") != startup.run_id
        or not same_proof({"path": host.get("temporal", {}).get("workflow_identity_path"),
                           "sha256": host.get("temporal", {}).get("workflow_identity_sha256")}, value["source_identity"])
        or not same_proof(config.get("role_host_binding"), value["source_host"]) or config.get("run_id") != startup.run_id):
        raise ValueError("recovery source Host/config is not the original frozen identity")
    read_proof(value["central_projection"], "central projection")
    for name in ("source_identity", "source_host", "source_config"):
        if Path(value[name]["path"]).resolve().is_relative_to(root.resolve()):
            raise ValueError("versioned outputs must not contain original frozen files")
    return dict(value), identity, checkpoint


async def source_snapshot(identity: Mapping[str, str]) -> tuple[dict, dict, dict]:
    from .workflows import StartSlkWorkflow
    client = await Client.connect(identity["address"])
    handles = {name: client.get_workflow_handle(identity[name + "_workflow_id"], run_id=identity[name + "_run_id"])
               for name in ("start", "run")}
    descriptions = await asyncio.gather(*(handles[name].describe() for name in ("start", "run")))
    executions = {}
    for name, description in zip(("start", "run"), descriptions):
        if (description.status != WorkflowExecutionStatus.FAILED or description.close_time is None
            or description.run_id != identity[name + "_run_id"] or description.task_queue != identity["task_queue"]):
            raise ValueError("source native pair is not the exact closed FAILED pair")
        executions[name] = {"status": "FAILED", "close_time": description.close_time.isoformat()}
    parent = await handles["start"].query(StartSlkWorkflow.status)
    if (parent.get("run_id") != identity["run_id"] or parent.get("child_workflow_id") != identity["run_workflow_id"]
        or parent.get("startup_fingerprint") != identity["startup_fingerprint"]):
        raise ValueError("source parent/child lineage changed")
    checkpoint = validate_checkpoint(await handles["run"].query("recovery_checkpoint"))
    histories = {name: json.loads((await handles[name].fetch_history()).to_json()) for name in ("start", "run")}
    return executions, checkpoint, histories


def _central(config: Mapping, startup: StartSlkRequest, checkpoint: Mapping, host: Mapping) -> dict:
    projection = adapter._query(config)
    runtime = projection.get("runtime_snapshot", {})
    summary = projection.get("summary", {})
    active = {}
    for row in projection.get("roles", []):
        if row.get("lifecycle") == "active":
            role = str(row.get("role", "")).upper()
            if role in active:
                raise ValueError("recovery team registry is ambiguous")
            active[role] = row.get("role_instance_id")
    packet = checkpoint["continuity"]["pending"]
    pending = packet["delivery"] if packet is not None else None
    pause = checkpoint.get("status", {}).get("run_pause")
    state = {"REQUESTED": "pause_requested", "PAUSED": "paused", "RESUMED": "active"}.get(
        pause["phase"] if pause else "RESUMED")
    if (projection.get("summary", {}).get("run_id") != startup.run_id
        or runtime.get("method_version") not in {"4.4.2", "4.4.3"} or runtime.get("plan_revision") != host.get("plan_revision")
        or type(runtime.get("runtime_revision")) is not int
        or pending is not None and (runtime["runtime_revision"] < pending["source_runtime_revision"]
            or runtime.get("token_holder_role_instance_id") != pending["sender_role_instance_id"])
        or pending is None and runtime.get("token_holder_role_instance_id") != (
            checkpoint.get("status", {}).get("responsible_role_instance_id") or startup.supervisor.role_instance_id)
        or active != {row.role: row.role_instance_id for row in startup.roles}
        or summary.get("state") != state or summary.get("closure_state") != "open"
        or summary.get("closed_at") is not None):
        raise ValueError("current central boundary/team no longer owns the original pending delivery")
    authority = adapter._run_json(list(config["transport_command"]), [
        "inspect-recovery-authority", "--binding", config["role_host_binding"]["path"],
        "--sha256", config["role_host_binding"]["sha256"],
        "--supervisor-role-instance-id", startup.supervisor.role_instance_id],
        environment={"SLK_CONFIG_PATH": str(config["state_config_path"])})
    if (authority.get("status") != "SUPERVISOR_RECOVERY_AUTHENTICATED"
        or authority.get("run_id") != startup.run_id
        or authority.get("supervisor_role_instance_id") != startup.supervisor.role_instance_id
        or authority.get("runtime_revision") != runtime["runtime_revision"]):
        raise ValueError("existing sealed Supervisor recovery authority is not proven")
    return projection


async def validate_source(request: dict, *, config_root: Path) -> dict:
    value, identity, checkpoint = validate_request(request)
    expected_config = config_root.resolve() / (value["run_id"] + ".json")
    if not same_proof(proof(expected_config), value["source_config"]):
        raise ValueError("recovery worker is not bound to the original source config")
    config = adapter._load_config(value["run_id"])
    executions, actual, histories = await source_snapshot(identity)
    if (executions != value["source_executions"] or actual != checkpoint
        or any(adapter._receipt(histories[name]) != adapter._receipt(read_proof(value["histories"][name], "history"))
               for name in ("start", "run"))):
        raise ValueError("source checkpoint/history changed")
    startup = StartSlkRequest.from_dict(checkpoint["startup"])
    host = read_proof(value["source_host"], "host")
    current = await asyncio.to_thread(_central, config, startup, checkpoint, host)
    if not same_central_boundary(read_proof(value["central_projection"], "central projection"), current):
        raise ValueError("central Run changed after recovery preparation")
    return {"status": "RECOVERY_READY", "checkpoint": checkpoint,
            "recovery_request_sha256": adapter._receipt(value), "source_run_id": identity["run_run_id"]}


def same_central_boundary(saved: dict, current: dict) -> bool:
    """Only the three existing append-only OW observation collections may grow."""
    collections = {"overwatch_cycles": "cycle_id", "operational_observations": "observation_id",
                   "overwatcher_native_status_receipts": "status_id"}
    if set(saved) != set(current):
        return False
    for key in saved:
        if key not in collections:
            if saved[key] != current[key]:
                return False
            continue
        old, new = saved[key], current[key]
        if not isinstance(old, list) or not isinstance(new, list):
            return False
        identifier = collections[key]
        if any(not isinstance(row, dict) or not isinstance(row.get(identifier), str) for row in old + new):
            return False
        by_id = {row[identifier]: row for row in new}
        if len(by_id) != len(new) or len({row[identifier] for row in old}) != len(old):
            return False
        if any(by_id.get(row[identifier]) != row for row in old):
            return False
    return True


async def prepare(*, identity_path: Path, identity_sha256: str, config_root: Path,
                  evidence_root: Path, reason: str, evidence_ref: str) -> dict:
    source = {"path": str(identity_path.resolve()), "sha256": identity_sha256}
    identity = _identity(read_proof(source, "source identity"))
    adapter.configure(config_root)
    config_path = config_root.resolve() / (identity["run_id"] + ".json")
    config = adapter._load_config(identity["run_id"])
    executions, checkpoint, histories = await source_snapshot(identity)
    startup = StartSlkRequest.from_dict(checkpoint["startup"])
    host = read_proof(config["role_host_binding"], "source host")
    projection = await asyncio.to_thread(_central, config, startup, checkpoint, host)
    root = evidence_root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    for name, packet in (("checkpoint", checkpoint), ("central-projection", projection),
                         ("start-history", histories["start"]), ("run-history", histories["run"])):
        _write_identity(root / (name + ".json"), packet)
    request = {"schema_version": "slk.temporal-execution-recovery/v1", "run_id": identity["run_id"],
        "source_identity": source, "source_executions": executions, "checkpoint": proof(root / "checkpoint.json"),
        "histories": {name: proof(root / (name + "-history.json")) for name in ("start", "run")},
        "source_host": config["role_host_binding"], "source_config": proof(config_path),
        "central_projection": proof(root / "central-projection.json"),
        "decision": {"supervisor_role_instance_id": startup.supervisor.role_instance_id,
                     "reason": reason, "evidence_ref": evidence_ref}, "evidence_root": str(root)}
    validate_request(request)
    _write_identity(root / "request.json", request)
    return proof(root / "request.json")


def materialize_bindings(request: Mapping, identity: dict) -> dict:
    """New immutable refs only; original Host/config/identity are never rewritten."""
    root = Path(request["evidence_root"])
    identity_path = root / "workflow-identity.json"
    _write_identity(identity_path, identity)
    host = read_proof(request["source_host"], "source host")
    host["temporal"] = {**host["temporal"], "workflow_identity_path": str(identity_path),
                        "workflow_identity_sha256": proof(identity_path)["sha256"]}
    host_path = root / "role-host.json"
    _write_identity(host_path, host)
    config = read_proof(request["source_config"], "source config")
    config["role_host_binding"] = proof(host_path)
    config_path = root / "adapter-config" / (request["run_id"] + ".json")
    _write_identity(config_path, config)
    return {"identity": proof(identity_path), "role_host": proof(host_path), "adapter_config": proof(config_path)}


def verify_restored_checkpoint(source: dict, target: object, *, initial: bool) -> None:
    from .continuity import RunContinuity
    if (not isinstance(target, Mapping) or set(target) != set(source)
        or target["schema_version"] != source["schema_version"] or target["startup"] != source["startup"]
        or target["admission_request_sha256"] != source["admission_request_sha256"]):
        raise ValueError("actual recovery changed startup/admission lineage")
    RunContinuity.from_checkpoint(target["continuity"])
    for key in ("seen", "completed", "abandoned"):
        old, new = source["continuity"][key], target["continuity"][key]
        if new[:len(old)] != old:
            raise ValueError("actual recovery lost or changed communication history")
    for key in ("delivery_started", "recovery_started"):
        if not set(source[key]) <= set(target[key]):
            raise ValueError("actual recovery lost activity identities")
    if initial:
        validate_checkpoint(target)
        old, new = source["status"], target["status"]
        allowed = {"next_overwatcher_audit_at"}
        if old["member_residency_notice_sent"] is False and new["member_residency_notice_sent"] is True:
            since = old["member_residency_since"]
            if since is None or datetime.fromisoformat(since) + timedelta(minutes=30) > datetime.now(timezone.utc):
                raise ValueError("recovery notice has no expired source responsibility")
            event = source["startup"]["run_id"] + "-member-residency-" + old["responsibility_operation_id"]
            failure = {"event_id": event, "reason": "SUPERVISOR_NOTIFICATION_UNPROVED"}
            supervisor = StartSlkRequest.from_dict(source["startup"]).supervisor.role_instance_id
            failed_guard = {"event_id": event, "kind": failure["reason"], "run_id": source["startup"]["run_id"],
                "responsible_role_instance_id": supervisor, "source_operation_id": "runtime-guard-" + event,
                "threshold_seconds": 0}
            expected_guard = old["runtime_guard_blocker"] or (failed_guard if new["notification_failure"] else None)
            if (new["notification_failure"] not in (None, failure)
                or new["runtime_guard_blocker"] != expected_guard):
                raise ValueError("recovery changed an unresolved guard or overdue notice identity")
            allowed |= {"member_residency_notice_sent", "notification_failure", "runtime_guard_blocker"}
        if (target["continuity"] != source["continuity"]
            or any(target[key] != source[key] for key in ("delivery_started", "recovery_started", "admission_requested"))
            or {k: v for k, v in new.items() if k not in allowed}
               != {k: v for k, v in old.items() if k not in allowed}):
            raise ValueError("actual recovery is not the exact ACK-only checkpoint")


async def verify_target(request: dict, identity: dict, checkpoint: dict, *, initial: bool) -> None:
    identity = _identity(identity)
    source = _identity(read_proof(request["source_identity"], "source identity"))
    suffix = "-recovery-" + source["run_run_id"]
    if (identity["start_workflow_id"] != "slk-start-" + request["run_id"] + suffix
        or identity["run_workflow_id"] != "slk-run-" + request["run_id"] + suffix
        or any(identity[key] != source[key] for key in ("run_id", "address", "task_queue", "startup_fingerprint"))):
        raise ValueError("recovery target changed source/target lineage")
    await inspect_pair(**{k: v for k, v in identity.items() if k != "schema_version"})
    client = await Client.connect(identity["address"])
    parent = await client.get_workflow_handle(identity["start_workflow_id"], run_id=identity["start_run_id"]).query("status")
    if parent.get("recovery_request_sha256") != adapter._receipt(request):
        raise ValueError("recovery target changed immutable request")
    target = await client.get_workflow_handle(identity["run_workflow_id"], run_id=identity["run_run_id"]).query("recovery_checkpoint")
    verify_restored_checkpoint(checkpoint, target, initial=initial)


async def restore(*, request_path: Path, request_sha256: str, config_root: Path) -> dict:
    from .workflows import StartSlkWorkflow
    request, source, checkpoint = validate_request(read_proof(
        {"path": str(request_path.resolve()), "sha256": request_sha256}, "recovery request"))
    adapter.configure(config_root)
    result_path = Path(request["evidence_root"]) / "result.json"
    if result_path.exists():
        saved = read_proof(proof(result_path), "saved recovery result")
        if (set(saved) != {"schema_version", "status", "run_id", "source_identity", "target_identity",
                           "request_sha256", "identity", "role_host", "adapter_config"}
            or saved["schema_version"] != "slk.temporal-execution-recovery-result/v1"
            or saved["status"] != "ACK_ONLY_PAIR_RUNNING" or saved["run_id"] != request["run_id"]
            or saved["source_identity"] != source or saved["request_sha256"] != request_sha256):
            raise ValueError("saved recovery result changed immutable lineage")
        for key in ("identity", "role_host", "adapter_config"):
            read_proof(saved[key], key)
        if materialize_bindings(request, saved["target_identity"]) != {k: saved[k] for k in ("identity", "role_host", "adapter_config")}:
            raise ValueError("saved recovery binding changed")
        await verify_target(request, saved["target_identity"], checkpoint, initial=False)
        return saved  # verified historical result; never re-admit or repeat work
    await validate_source(request, config_root=config_root)
    startup = StartSlkRequest.from_dict(checkpoint["startup"])
    suffix = "-recovery-" + source["run_run_id"]
    parent_id, child_id = "slk-start-" + startup.run_id + suffix, "slk-run-" + startup.run_id + suffix
    client = await Client.connect(source["address"])
    handle = await client.start_workflow(StartSlkWorkflow.run, {"recovery": request}, id=parent_id,
        task_queue=startup.task_queue, id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE,
        id_conflict_policy=WorkflowIDConflictPolicy.USE_EXISTING)
    async def pair():
        while True:
            status = await handle.query(StartSlkWorkflow.status)
            if status.get("phase") in {"PAIR_CREATED", "RUNNING"}:
                if (status.get("recovery_request_sha256") != adapter._receipt(request)
                    or status.get("child_workflow_id") != child_id):
                    raise ValueError("existing recovery changed the immutable disposition/checkpoint")
                parent, child = await asyncio.gather(handle.describe(), client.get_workflow_handle(child_id).describe())
                return {**source, "start_workflow_id": parent_id, "start_run_id": parent.run_id,
                        "run_workflow_id": child_id, "run_run_id": child.run_id}
            await asyncio.sleep(0.1)
    identity = await asyncio.wait_for(pair(), 30)
    await verify_target(request, identity, checkpoint, initial=True)
    bindings = materialize_bindings(request, identity)
    result = {"schema_version": "slk.temporal-execution-recovery-result/v1", "status": "ACK_ONLY_PAIR_RUNNING",
              "run_id": startup.run_id, "source_identity": source, "target_identity": identity,
              "request_sha256": request_sha256, **bindings}
    _write_identity(Path(request["evidence_root"]) / "result.json", result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    preparation = commands.add_parser("prepare")
    preparation.add_argument("--identity", type=Path, required=True)
    preparation.add_argument("--identity-sha256", required=True)
    preparation.add_argument("--evidence-root", type=Path, required=True)
    preparation.add_argument("--reason", required=True)
    preparation.add_argument("--evidence-ref", required=True)
    recovery = commands.add_parser("restore")
    recovery.add_argument("--request", type=Path, required=True)
    recovery.add_argument("--request-sha256", required=True)
    for command in (preparation, recovery):
        command.add_argument("--standard-config-root", type=Path, required=True)
    args = vars(parser.parse_args())
    command = args.pop("command")
    args["config_root"] = args.pop("standard_config_root")
    if command == "prepare":
        args["identity_path"] = args.pop("identity")
    else:
        args["request_path"] = args.pop("request")
    print(json.dumps(asyncio.run((prepare if command == "prepare" else restore)(**args)), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
