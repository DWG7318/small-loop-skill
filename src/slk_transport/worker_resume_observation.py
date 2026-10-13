"""Read-only native continuation selection beneath an authenticated original source."""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping

from . import native_activity as native, worker_completion as wc


MAX_NATIVE_RESUMES = 64
MARKER_FIELDS = {"schema_version", "invocation_id", "original_source", "original_source_sha256",
                 "binding_sha256", "instructions_sha256", "coordinator_process"}


def _not_alternate(path: Path) -> None:
    if path.is_symlink() or getattr(path, "is_junction", lambda: False)():
        raise native.NativeActivityError("native resume evidence must not use symlinks or junctions")


def _file(path: Path, *, required: bool = False) -> None:
    _not_alternate(path)
    if (path.exists() and not path.is_file()) or (required and not path.is_file()):
        raise native.NativeActivityError("native resume evidence is not a regular file")


@dataclass(frozen=True)
class WorkerResumeObservation:
    source: Path
    started_path: Path | None
    metadata: dict[str, Any]

    def inspect_native(self, inspector: Callable[..., dict], *, observed_at: str | None = None) -> dict:
        if self.started_path is None:
            return {"schema_version": native.ACTIVITY_SCHEMA, "status": "UNKNOWN",
                "observed_at": observed_at or native.utc_now(), "process": None, "native_task": None,
                "last_event": None, "waiting_on": None, "terminal_evidence": None,
                "error": "NATIVE_RESUME_START_PENDING"}
        result = inspector(self.started_path,
            terminal_paths=(self.source / "completed.json", self.source / "failed.json"),
            **({"observed_at": observed_at} if observed_at is not None else {}))
        if native.sha256_file(self.started_path) != self.metadata["native_start_sha256"]:
            raise native.NativeActivityError("selected native resume start changed during query")
        return result


def select_worker_resume(original_source: Path, *, endpoint: Mapping[str, Any],
                         envelope: Mapping[str, Any], original_start: Mapping[str, Any]) -> WorkerResumeObservation | None:
    """Join only direct, closed resume evidence after the caller checks central scope.

    The marker's binding hash is disclosed provenance, not observer authority.
    Launch already authenticated its Supervisor; observation never unwraps a
    credential or replaces the original central delivery proof.
    """
    source = Path(original_source)
    resumes = source / "native-resumes"
    _not_alternate(resumes)
    if not resumes.exists():
        return None
    _not_alternate(source)
    if not resumes.is_dir():
        raise native.NativeActivityError("native resume root must be a directory")
    entries = []
    for child in resumes.iterdir():
        if len(entries) >= MAX_NATIVE_RESUMES:
            raise native.NativeActivityError("native resume observation exceeds its bounded direct entries")
        _not_alternate(child)
        if not child.is_dir() or str(uuid.UUID(child.name)) != child.name:
            raise native.NativeActivityError("native resume directory must be one canonical UUID")
        entries.append(child)
    if not entries:
        return None
    session = endpoint.get("address", {}).get("session_id")
    if (endpoint.get("role") != "worker" or endpoint.get("adapter") != "dsh-worker"
        or not isinstance(session, str) or not session
        or source.name != envelope.get("message_id") or source.parent.name != envelope.get("run_id")
        or original_start.get("native_task") != {"kind": "dsh-session", "id": session, "status": "RUNNING"}):
        raise native.NativeActivityError("native resume original is not the exact Worker Session/task")
    original_time = wc._timestamp(original_start["observed_at"])
    for name in ("endpoint.json", "envelope.json", "started.json", "completed.json", "failed.json",
                 "worker-result.json", "checker-result.json", "ocrv-result.json"):
        _file(source / name)
    _not_alternate(source / "incomplete-handoff")
    _file(source / "incomplete-handoff" / "evidence.json")
    from .role_host import RoleHost
    original_sha256 = RoleHost._source_sha256(source, "worker")
    started, pending, live = [], [], []
    for child in entries:
        for name in ("native-resume.json", "endpoint.json", "envelope.json", "instructions.md"):
            _file(child / name, required=True)
        for name in ("started.json", "completed.json", "failed.json", "native-activity.json", "worker-result.json"):
            _file(child / name)
        _not_alternate(child / "role-host")
        marker = wc._read_object(child / "native-resume.json", "native continuation")
        coordinator = marker.get("coordinator_process")
        if (set(marker) != MARKER_FIELDS or marker.get("schema_version") != "slk.worker-native-resume/v1"
            or marker.get("invocation_id") != child.name
            or marker.get("original_source") != str(source.resolve())
            or marker.get("original_source_sha256") != original_sha256
            or not isinstance(marker.get("binding_sha256"), str)
            or not native.SHA256.fullmatch(marker["binding_sha256"])
            or marker.get("instructions_sha256") != wc._sha256(child / "instructions.md")
            or not isinstance(coordinator, Mapping) or set(coordinator) != native.PROCESS_FIELDS
            or type(coordinator.get("pid")) is not int or coordinator["pid"] < 1
            or not isinstance(coordinator.get("creation_time"), str) or not coordinator["creation_time"].strip()
            or wc._read_object(child / "endpoint.json", "continued endpoint") != endpoint
            or wc._read_object(child / "envelope.json", "continued envelope") != envelope):
            raise native.NativeActivityError("native resume changed its closed original responsibility/provenance")
        path = child / "started.json"
        metadata = {"invocation_id": child.name, "native_start_path": str(path), "native_start_sha256": None}
        if not path.is_file():
            if any((child / name).exists() for name in ("completed.json", "failed.json")):
                raise native.NativeActivityError("native resume terminal has no native start")
            pending.append(WorkerResumeObservation(child, None, metadata))
            continue
        start = native.validate_native_start(path, adapter=endpoint["adapter"], run_id=envelope["run_id"],
            cell_id=envelope["cell_id"], message_id=envelope["message_id"], request_sha256=envelope["payload_sha256"])
        if start["native_task"] != original_start["native_task"]:
            raise native.NativeActivityError("native resume changed its exact original DSH Session")
        timestamp = wc._timestamp(start["observed_at"])
        if timestamp <= original_time or timestamp > wc._timestamp(native.utc_now()):
            raise native.NativeActivityError("native resume start time is not a genuine later activation")
        terminal, _path, error = native._terminal_result(start, (child / "completed.json", child / "failed.json"))
        if error is not None:
            raise native.NativeActivityError(error)
        metadata["native_start_sha256"] = native.sha256_file(path)
        observation = WorkerResumeObservation(child, path, metadata)
        started.append((timestamp, observation))
        if terminal is None:
            process = native.process_probe(**start["process"])
            if process["exists"] and process["identity_matches"]:
                live.append(observation)
    if len(live) > 1 or len(pending) > 1 or (pending and live):
        raise native.NativeActivityError("ambiguous live or pending native resume activations")
    if pending:
        return pending[0]
    started.sort(key=lambda item: item[0])
    if len(started) > 1 and started[-1][0] == started[-2][0]:
        raise native.NativeActivityError("ambiguous native resume start timestamps")
    latest = started[-1][1]
    if live and live[0].source != latest.source:
        raise native.NativeActivityError("ambiguous older native resume remains live")
    return latest
