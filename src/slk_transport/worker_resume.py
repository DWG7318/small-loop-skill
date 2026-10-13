"""Supervisor-authorized native continuation, not another logical delivery."""
from __future__ import annotations

import json
import os
import uuid
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path
from typing import Mapping

from . import native_activity as native, worker_completion as wc
from .adapters.base import AdapterError
from .adapters.dsh import DshAdapter
from .contracts import DeliveryResult, Envelope, parse_delivery
from .evidence import Attempt
from .worker_session_stop import native_session_stopped


@contextmanager
def invocation_environment(values):
    previous = {key: os.environ.get(key) for key in values}
    try:
        os.environ.update(values)
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def source_identity(source: Path, host, envelope: Envelope) -> str:
    """The business message stays unchanged; each native retry has its own output ID."""
    marker = source / "native-resume.json"
    if source.parent.name != "native-resumes":
        if marker.exists():
            raise ValueError("native continuation is outside its original source")
        return envelope.message_id
    value = wc._read_object(marker, "native continuation")
    original = source.parent.parent
    if (set(value) != {"schema_version", "invocation_id", "original_source", "original_source_sha256",
                      "binding_sha256", "instructions_sha256", "coordinator_process"}
        or value["schema_version"] != "slk.worker-native-resume/v1"
        or value["invocation_id"] != source.name
        or str(uuid.UUID(source.name)) != source.name
        or Path(value["original_source"]).resolve() != original.resolve()
        or value["binding_sha256"] != host.digest
        or value["original_source_sha256"] != host._source_sha256(original, "worker")
        or wc._read_object(original / "endpoint.json", "original endpoint") != host.endpoint("worker")
        or wc._read_object(original / "envelope.json", "original envelope") != asdict(envelope)
        or wc._read_object(source / "endpoint.json", "continued endpoint") != host.endpoint("worker")
        or value["instructions_sha256"] != wc._sha256(source / "instructions.md")
        or any(path.is_symlink() for path in (source, source.parent, original))):
        raise ValueError("native continuation changed its exact original responsibility")
    return wc._stable_id(envelope.message_id, "native-resume:" + source.name)


def require_live_action(source: Path) -> None:
    if any((source / name).exists() for name in ("completed.json", "failed.json")):
        raise ValueError("ended native invocation cannot submit a new Worker action")
    start = native.validate_native_start(source / "started.json")
    activity = native.validate_native_task_activity(wc._read_object(source / "native-activity.json", "native activity"),
        adapter=start["adapter"], run_id=start["run_id"], cell_id=start["cell_id"],
        message_id=start["message_id"], native_task_id=start["native_task"]["id"])
    process = start["process"]
    live = native.process_probe(process["pid"], process["creation_time"])
    if activity["status"] != "RUNNING" or not live["exists"] or not live["identity_matches"]:
        raise ValueError("Worker action requires the actual live native invocation")


def _stopped(source: Path, envelope: Envelope, session: str) -> None:
    start = native.validate_native_start(source / "started.json", adapter="dsh-worker", run_id=envelope.run_id,
        cell_id=envelope.cell_id, message_id=envelope.message_id, request_sha256=envelope.payload_sha256)
    if start["native_task"] != {"kind": "dsh-session", "id": session, "status": "RUNNING"}:
        raise ValueError("native continuation must use the registered original DSH Session")
    process = start["process"]
    live = native.process_probe(process["pid"], process["creation_time"])
    if live["exists"] and live["identity_matches"]:
        raise ValueError("original native invocation is still running")
    terminals = [source / name for name in ("completed.json", "failed.json") if (source / name).is_file()]
    if len(terminals) != 1:
        raise ValueError("original native invocation has no unique terminal result")
    terminal = DeliveryResult.from_dict(wc._read_object(terminals[0], "original terminal"))
    if (terminal.message_id, terminal.run_id, terminal.adapter) != (envelope.message_id, envelope.run_id, "dsh-worker"):
        raise ValueError("original native terminal changed identity")


class _ContinuationAdapter(DshAdapter):
    def __init__(self, instructions: Path, digest: str):
        super().__init__()
        self.instructions, self.digest = instructions, digest

    def task_instruction(self, task_path: Path, task_sha256: str) -> str:
        return (super().task_instruction(task_path, task_sha256)
            + " This is a new native activation of the SAME logical task/Session/attempt, not D1 rework. "
            + "Use MCP slk_worker_action for WORK_STARTED/D0_COMPLETED/CANDIDATE_SUBMITTED; do not use shell to write central state. "
            + "Finish work and D0, save original output, then submit candidate as the final work action and return. "
            + f"Read Supervisor continuation instructions at {json.dumps(str(self.instructions))}, SHA256 {self.digest}. "
            + "Do not copy the previous blocked result or claim the old invocation is active.")


def resume_worker_session(host, source: Path, *, invocation_id: str, instructions_path: Path,
                          instructions_sha256: str, adapter=None) -> dict:
    source = source.resolve()
    if str(uuid.UUID(invocation_id)) != invocation_id:
        raise ValueError("native invocation ID must be one canonical UUID")
    endpoint_raw = host.endpoint("worker")
    parsed = parse_delivery(endpoint_raw, wc._read_object(source / "envelope.json", "original Worker envelope"))
    endpoint, envelope = parsed.endpoint, parsed.envelope
    if (wc._read_object(source / "endpoint.json", "original Worker endpoint") != endpoint_raw
        or source.name != envelope.message_id or source.parent.name != envelope.run_id
        or endpoint.adapter != "dsh-worker" or not endpoint.address.get("session_id")):
        raise ValueError("native recovery requires the exact original registered Worker source")
    if "temporal" in host.binding and source != (Path(host.binding["temporal"]["attempt_root"]) / envelope.run_id / envelope.message_id).resolve():
        raise ValueError("native recovery source is not the canonical Run attempt")
    supervisor = host.endpoint("supervisor")
    if supervisor["adapter"] == "codex-app-server" and os.environ.get("CODEX_THREAD_ID") != supervisor["address"]["thread_id"]:
        raise ValueError("only the registered Supervisor may resume this Worker")
    host.inspect_recovery_authority(supervisor["role_instance_id"])
    projection = host._boundary(envelope)
    if projection.get("summary", {}).get("state") in {"closed", "archived", "paused", "pause_requested"}:
        raise ValueError("Run lifecycle does not allow native Worker continuation")
    session = str(endpoint.address["session_id"])
    _stopped(source, envelope, session)
    stop_proof = native_session_stopped(endpoint)
    if wc._sha256(instructions_path) != instructions_sha256:
        raise ValueError("Supervisor continuation instructions changed")
    resumes = source / "native-resumes"
    sources = [source]
    if resumes.is_symlink():
        raise ValueError("native resume root must not be an alternate path")
    if resumes.exists():
        for prior in resumes.iterdir():
            if not prior.is_dir() or prior.is_symlink():
                raise ValueError("unexpected native resume entry")
            source_identity(prior, host, envelope)
            sources.append(prior)
            if (prior / "started.json").is_file():
                _stopped(prior, envelope, session)
            else:
                process = wc._read_object(prior / "native-resume.json", "native continuation")["coordinator_process"]
                live = native.process_probe(process["pid"], process["creation_time"])
                if live["exists"] and live["identity_matches"]:
                    raise ValueError("another native recovery is still starting")
    submitted = [event for event in projection.get("events", [])
        if event.get("event_type") == "CANDIDATE_SUBMITTED"
        and event.get("go_id") == envelope.go_id and event.get("cell_id") == envelope.cell_id
        and event.get("author_role_instance_id") == envelope.receiver_role_instance_id
        and wc._event_details(event).get("source_message_id") == envelope.message_id]
    candidates = [path for path in sources if (path / "role-host/worker-candidate_submitted.json").exists()]
    if submitted or candidates:
        if (len(submitted) != 1 or len(candidates) != 1
            or wc._read_object(candidates[0] / "role-host/worker-candidate_submitted.json", "original candidate").get("event_id")
                != submitted[0].get("event_id")):
            raise ValueError("recorded candidate requires its unique original action evidence; do not restart work")
        candidate = candidates[0]
        terminal = next(candidate / name for name in ("completed.json", "failed.json") if (candidate / name).is_file())
        # Keep the original provider outcome. Existing Host validation consumes
        # the exact saved candidate and only its still-missing delivery stages.
        return {"status": "CANDIDATE_HANDOFF_ONLY", "run_id": envelope.run_id,
            "source_message_id": envelope.message_id, "invocation_id": None,
            "invocation_path": str(candidate), "native_result": wc._read_object(terminal, "original terminal"),
            "output_delivery": host.complete(candidate)}
    root = resumes / invocation_id
    try:
        root.mkdir(parents=True, exist_ok=False)
    except FileExistsError as exc:
        raise ValueError("native invocation already exists; use its saved output, never relaunch it") from exc
    attempt = Attempt(root)
    attempt.write_json_once("native-session-stop.json", stop_proof)
    attempt.write_json_once("endpoint.json", endpoint_raw)
    attempt.write_json_once("envelope.json", asdict(envelope))
    attempt.write_bytes_once("instructions.md", instructions_path.read_bytes())
    if wc._sha256(root / "instructions.md") != instructions_sha256:
        raise ValueError("Supervisor instructions changed while copying")
    marker = attempt.write_json_once("native-resume.json", {
        "schema_version": "slk.worker-native-resume/v1", "invocation_id": invocation_id,
        "original_source": str(source), "original_source_sha256": host._source_sha256(source, "worker"),
        "binding_sha256": host.digest, "instructions_sha256": instructions_sha256,
        "coordinator_process": {"pid": os.getpid(), "creation_time": native.process_creation_time(os.getpid())}})
    attempt.write_json_once("accepted.json", {"status": "NATIVE_RESUME_REQUESTED", "invocation_id": invocation_id})
    environment = {"SLK_NATIVE_ACTIVITY_PATH": str(root / "native-activity.json"),
        "SLK_NATIVE_ACTIVITY_CONTEXT": json.dumps({"adapter": endpoint.adapter, "run_id": envelope.run_id,
            "cell_id": envelope.cell_id, "message_id": envelope.message_id}),
        "SLK_WORKER_NATIVE_RESUME_SHA256": wc._sha256(marker)}
    with invocation_environment(environment):
        try:
            result = (adapter or _ContinuationAdapter(root / "instructions.md", instructions_sha256)).deliver(endpoint, envelope, attempt)
            if (result.message_id, result.run_id, result.adapter) != (envelope.message_id, envelope.run_id, endpoint.adapter):
                raise ValueError("native continuation result changed scope")
        except AdapterError as exc:
            result = DeliveryResult("slk.transport-result/v1", envelope.message_id, envelope.run_id,
                endpoint.adapter, "failed", {}, exc.error_code, ())
        attempt.write_json_once("completed.json" if result.status == "completed" else "failed.json", result.to_dict())
        try:
            output = host.complete(root)
        except (ValueError, OSError) as exc:
            output = {"status": "HOST_HANDOFF_FAILED", "error_code": getattr(exc, "error_code", type(exc).__name__)}
            attempt.write_json_once("handoff-failed.json", output)
    return {"status": result.status, "run_id": envelope.run_id, "source_message_id": envelope.message_id,
        "invocation_id": invocation_id, "invocation_path": str(root), "native_result": result.to_dict(), "output_delivery": output}
