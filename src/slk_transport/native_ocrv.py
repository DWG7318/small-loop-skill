"""Read the exact original OCRV Session; never publish private native payloads."""
from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from .native_activity import TASK_ACTIVITY_SCHEMA, _atomic_json, process_probe, sha256_file, utc_now, validate_native_start


def _object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError("native evidence is not an object")
    return value


def _session(path: Path, source: Mapping[str, Any], request: Mapping[str, Any]) -> dict[str, Any] | None:
    """Stream originals, retaining only header/input hashes and public action metadata."""
    marker = str(source["marker"])
    header = input_proof = last = None
    sequence = 0
    ended = False
    terminal_event = None
    conflict = False
    with path.open("rb") as stream:
        for raw in stream:
            # An incomplete append is not a new native fact. Private response
            # records need no JSON decoding and are never copied into evidence.
            if not raw.endswith(b"\n"):
                break
            kind_match = re.search(br'"type"\s*:\s*"(session_start|llm_request|tool_call|session_end)"', raw)
            if kind_match is None:
                continue
            kind = kind_match[1].decode("ascii")
            if kind == "llm_request" and (input_proof is not None or marker.encode() not in raw):
                continue
            row = json.loads(raw)
            if row.get("type") != kind:
                continue
            if kind == "session_start" and not ended:
                if header is not None or row.get("sessionId") != path.stem:
                    raise ValueError("native header is not unique")
                if os.path.normcase(str(Path(row["cwd"]).resolve())) != os.path.normcase(str(Path(request["repository"]).resolve())):
                    return None
                candidate = request["candidate"]
                if candidate["kind"] == "commit" and row.get("diffCommit") != candidate["commit"]:
                    return None
                if candidate["kind"] == "range" and (row.get("diffFrom"), row.get("diffTo")) != (candidate["from"], candidate["to"]):
                    return None
                endpoint_source = row.get("llmSource")
                provider = (endpoint_source.removeprefix("provider:")
                            if isinstance(endpoint_source, str) and endpoint_source.startswith("provider:") else None)
                header = {"session_id": row["sessionId"], "header_sha256": hashlib.sha256(raw).hexdigest(),
                          "provider": provider, "model": row.get("model"), "endpoint_source": endpoint_source}
            elif header is None or row.get("sessionId") != header["session_id"]:
                raise ValueError("native action changed Session identity")
            if kind == "llm_request":
                if any(isinstance(message, dict) and isinstance(message.get("content"), str)
                       and marker in message["content"].splitlines() for message in row.get("messages", [])):
                    input_proof = {"input_record_uuid": row["uuid"], "input_record_sha256": hashlib.sha256(raw).hexdigest()}
                continue
            sequence += 1
            last = {"kind": {"session_start": "OCRV_SESSION_START", "tool_call": "OCRV_TOOL_CALL",
                             "session_end": "OCRV_SESSION_END"}[kind],
                    "sequence": sequence, "session_id": row["sessionId"], "observed_at": row["timestamp"]}
            if kind == "tool_call":
                last.update({key: row[key] for key in ("tool_name", "ok", "duration_ms")})
            public_record = {"kind": last["kind"], "sequence": sequence, "observed_at": row["timestamp"],
                             "detail_sha256": hashlib.sha256(raw).hexdigest()}
            if ended:
                conflict = True
                last["tail"] = [terminal_event, public_record]
            if kind == "session_end":
                last["duration_seconds"] = row["duration_seconds"]
                if not ended:
                    terminal_event = public_record
                ended = True
    if header is None or input_proof is None:
        return None
    return {**header, **input_proof, "last_event": last, "sequence": sequence, "ended": ended, "conflict": conflict}


def inspect_ocrv_session(started_path: Path, start: Mapping[str, Any], *, include_identity: bool = False) -> Mapping[str, Any]:
    """Original reader path, no scheduler or history collector. Binding is immutable."""
    unknown = {"status": "UNKNOWN", "error": "OCRV_NATIVE_SESSION_UNPROVEN", "last_event": None, "waiting_on": None}
    try:
        source_path = started_path.with_name("ocrv-native-source.json")
        source = _object(source_path)
        receipt_path = started_path.with_name("native-start.received.json")
        # Transport publishes validated JSON with its own deterministic encoding.
        # Keep the producer's byte proof AND full authoritative-start semantics.
        if (source.get("schema_version") != "slk.ocrv-native-source/v1"
            or source["native_start_sha256"] != sha256_file(receipt_path)
            or validate_native_start(receipt_path) != dict(start)
            or any(source[key] != start[key] for key in ("run_id", "cell_id", "message_id"))
            or source["invocation_id"] != start["native_task"]["id"]
            or sha256_file(Path(source["request_path"])) != start["native_request_sha256"]
            or sha256_file(Path(source["background_path"])) != source["background_sha256"]
            or source["marker"] != f"SLK_NATIVE_INVOCATION={source['invocation_id']};REQUEST_SHA256={start['native_request_sha256']}"):
            return unknown
        request = _object(Path(source["request_path"]))
        if Path(source["background_path"]).read_text(encoding="utf-8").splitlines()[0] != source["marker"]:
            return unknown
        directory = Path(source["session_directory"])
        binding_path = started_path.with_name("ocrv-session-binding.json")
        source_sha256 = sha256_file(source_path)
        if binding_path.is_file():
            binding = _object(binding_path)
            path = Path(binding["session_path"])
            if (binding.get("schema_version") != "slk.ocrv-session-binding/v1"
                or binding["source_sha256"] != source_sha256 or path.parent.resolve() != directory.resolve()):
                return unknown
            native = _session(path, source, request)
            if native is None or any(binding[key] != native[key] for key in (
                "session_id", "header_sha256", "input_record_uuid", "input_record_sha256")):
                return unknown
        else:
            # Prelaunch filename set rules out historical same-cwd Sessions.
            # A native resume creates a fresh ID; the explicitly resumed ID is
            # also allowed only if its own input carries this exact marker.
            prior = set(source["prior_sessions"])
            candidates = [path for path in directory.glob("*.jsonl")
                          if path.name not in prior or path.stem == source.get("resume_session_id")]
            matches = [(path, value) for path in candidates if (value := _session(path, source, request)) is not None]
            if len(matches) != 1:
                return unknown
            path, native = matches[0]
            binding = {"schema_version": "slk.ocrv-session-binding/v1", "source_sha256": source_sha256,
                "session_path": str(path.resolve()), **{key: native[key] for key in (
                    "session_id", "header_sha256", "input_record_uuid", "input_record_sha256")}}
            _atomic_json(binding_path, binding)
        result = {"schema_version": TASK_ACTIVITY_SCHEMA, **{key: start[key] for key in (
            "adapter", "run_id", "cell_id", "message_id")}, "native_task_id": start["native_task"]["id"],
            "status": "COMPLETED" if native["ended"] else "RUNNING", "sequence": native["sequence"],
            "observed_at": utc_now(), "last_event": native["last_event"], "waiting_on": None}
        if include_identity:  # Result projection only; do not widen the activity wire contract.
            result["native_identity"] = {key: native[key] for key in (
                "session_id", "provider", "model", "endpoint_source")}
        if native["conflict"]:
            return {**result, "status": "UNKNOWN", "error": "OCRV_SESSION_EVENT_AFTER_END"}
        if not native["ended"]:
            result.update(status="UNKNOWN", error="OCRV_SESSION_STATUS_UNAVAILABLE")
            try:
                process = _object(started_path.with_name("ocrv-native-process.json"))
                index = _object(Path(process["index_path"]))
                keys = ("run_id", "cell_id", "message_id", "native_request_sha256")
                if (process.get("schema_version") != "slk.ocrv-native-process/v1"
                    or any(process[key] != start[key] or index[key] != start[key] for key in keys)
                    or process["native_task_id"] != start["native_task"]["id"]
                    or index["native_task_id"] != process["native_task_id"]
                    or process["launcher_process"] != start["process"]
                    or process["native_start_sha256"] != source["native_start_sha256"]
                    or sha256_file(Path(process["index_path"])) != process["index_sha256"]):
                    return result
                identity = process["process"]
                live = process_probe(identity["pid"], identity["creation_time"])
                result["last_event"] = {**result["last_event"], "native_process": identity,
                                        "native_process_state": live}
                if live == {"exists": True, "identity_matches": True}:
                    result["status"] = "RUNNING"
                    result.pop("error")
            except (OSError, ValueError, KeyError, TypeError):
                pass  # Session identity/last action remain proven; live status is unknown.
        return result
    except (OSError, ValueError, TypeError, KeyError, IndexError):
        return unknown


def require_stopped_ocrv(receipt: Path, start: Mapping[str, Any]) -> None:
    """Exact original launcher AND executor must be stopped before recovery.

    A D1 record or session_end is not proof that the native writer exited.
    Reuse the MCP process/index binding; missing or unqueryable identity fails
    closed instead of treating the launcher's disappearance as executor exit.
    """
    process = _object(receipt.with_name("ocrv-native-process.json"))
    index = _object(Path(process["index_path"]))
    keys = ("run_id", "cell_id", "message_id", "native_request_sha256")
    if (process.get("schema_version") != "slk.ocrv-native-process/v1"
        or any(process.get(key) != start[key] or index.get(key) != start[key] for key in keys)
        or process.get("native_task_id") != start["native_task"]["id"]
        or index.get("native_task_id") != process["native_task_id"]
        or process.get("launcher_process") != start["process"]
        or process.get("native_start_sha256") != sha256_file(receipt)
        or sha256_file(Path(process["index_path"])) != process.get("index_sha256")):
        raise ValueError("original OCRV executor proof changed")
    for identity in (start["process"], process["process"]):
        if (not isinstance(identity, Mapping) or set(identity) != {"pid", "creation_time"}
            or type(identity["pid"]) is not int or identity["pid"] < 1
            or not isinstance(identity["creation_time"], str) or not identity["creation_time"]):
            raise ValueError("original OCRV process identity is unavailable")
        live = process_probe(identity["pid"], identity["creation_time"])
        if live["exists"] and live["identity_matches"]:
            raise ValueError("original OCRV writer is still alive; recorded D1 is not a sealed result")


def ocrv_resume_identity(source: Path, host, envelope, *, historical_hosts=None) -> str:
    """Validate a bounded descendant of the exact original Checker source.

    The logical message/D1 stays unchanged. Only public report delivery gets a
    distinct identity for this explicit native activation, as for Worker resume.
    """
    from dataclasses import asdict
    from . import worker_completion as wc
    current = Path(source)
    identity = envelope.message_id
    while True:
        if historical_hosts is not None and current.parent.name == "review-corrections":
            marker = wc._read_object(current / "ocrv-resume.json", "OCRV recovery provenance")
            host = historical_hosts.get(marker.get("binding_sha256"))
            if host is None:
                raise ValueError("OCRV recovery lacks its exact frozen historical Host reference")
        if any(path.is_symlink() or getattr(path, "is_junction", lambda: False)()
               for path in (current, current.parent)):
            raise ValueError("OCRV recovery cannot follow an alternate source")
        if (envelope.receiver_role != "checker"
            or wc._read_object(current / "endpoint.json", "Checker source") != host.endpoint("checker")
            or wc._read_object(current / "envelope.json", "Checker source") != asdict(envelope)):
            raise ValueError("OCRV recovery changed its original Checker scope")
        if current.parent.name != "review-corrections":
            if ((current / "ocrv-resume.json").exists() or current.name != envelope.message_id
                or current.parent.name != envelope.run_id
                or ("temporal" in host.binding and current.resolve() !=
                    (Path(host.binding["temporal"]["attempt_root"]) / envelope.run_id / envelope.message_id).resolve())):
                raise ValueError("OCRV recovery requires the exact original source")
            return identity
        marker = wc._read_object(current / "ocrv-resume.json", "OCRV recovery provenance")
        original = current.parent.parent
        if (set(marker) != {"schema_version", "invocation_id", "original_source", "original_source_sha256",
                            "binding_sha256", "resume_session_id", "coordinator_process"}
            or marker["schema_version"] != "slk.ocrv-native-resume/v1"
            or str(uuid.UUID(current.name)) != current.name or marker["invocation_id"] != current.name
            or marker["original_source"] != str(original.resolve())
            or marker["original_source_sha256"] != host._source_sha256(original, "checker")
            or marker["binding_sha256"] != host.digest
            or not isinstance(marker["resume_session_id"], str) or not marker["resume_session_id"]
            or not isinstance(marker["coordinator_process"], dict)
            or set(marker["coordinator_process"]) != {"pid", "creation_time"}
            or type(marker["coordinator_process"]["pid"]) is not int
            or marker["coordinator_process"]["pid"] < 1
            or not isinstance(marker["coordinator_process"]["creation_time"], str)
            or not marker["coordinator_process"]["creation_time"]):
            raise ValueError("OCRV recovery changed its bound original provenance")
        if current == source:
            identity = wc._stable_id(envelope.message_id, "ocrv-resume:" + current.name)
        current = original


@dataclass(frozen=True)
class OcrvResumeObservation:
    source: Path
    started_path: Path | None
    metadata: dict[str, Any]

    def inspect_native(self, inspector):
        from . import native_activity as native
        if self.started_path is None:
            return {"schema_version": native.ACTIVITY_SCHEMA, "status": "UNKNOWN", "observed_at": utc_now(),
                "process": None, "native_task": None, "last_event": None, "waiting_on": None,
                "terminal_evidence": None, "error": "OCRV_RESUME_START_PENDING"}
        terminals = (self.source / "completed.json", self.source / "failed.json")
        if any(path.exists() for path in terminals):
            require_stopped_ocrv(self.source / "native-start.received.json", validate_native_start(self.started_path))
        result = inspector(self.started_path, terminal_paths=terminals)
        if sha256_file(self.started_path) != self.metadata["native_start_sha256"]:
            raise ValueError("selected OCRV resume start changed during query")
        return result


def select_ocrv_resume(original_source: Path, *, endpoint: Mapping[str, Any],
                       envelope: Mapping[str, Any], original_start: Mapping[str, Any]) -> OcrvResumeObservation | None:
    """Read the unique explicit continuation chain; never authorize new work.

    The caller already authenticated the central original source. As in Worker
    observation, the marker's binding digest is disclosed provenance, not an
    observer credential. Reuse the launch identity validator without unsealing
    any role credential or requiring the observer to inherit Host environment.
    """
    from types import SimpleNamespace
    from . import native_activity as native
    from .contracts import Envelope
    from .role_host import RoleHost
    def regular(path: Path) -> None:
        if path.is_symlink() or getattr(path, "is_junction", lambda: False)():
            raise ValueError("OCRV resume observation cannot follow symlinks or junctions")
    current, selected, observer = Path(original_source), None, None
    parent_start = original_start
    while True:
        root = current / "review-corrections"
        regular(root)
        if not root.exists():
            return selected
        if not root.is_dir():
            raise ValueError("OCRV resume root is not a directory")
        children = iter(root.iterdir())
        child = next(children, None)
        if child is None or next(children, None) is not None:
            raise ValueError("OCRV resume has no unique valid leaf")
        regular(child)
        if not child.is_dir() or endpoint.get("role") != "checker" or endpoint.get("adapter") != "ocrv-checker":
            raise ValueError("OCRV resume changed its original Checker scope")
        for source in (current, child):
            regular(source)
            for name in ("endpoint.json", "envelope.json", "started.json", "native-start.received.json",
                         "ocrv-request.json", "ocrv-resume.json", "ocrv-native-source.json", "ocrv-native-process.json",
                         "ocrv-session-binding.json", "completed.json", "failed.json", "ocrv-result.json"):
                regular(source / name)
        marker = _object(child / "ocrv-resume.json")
        if observer is None:
            digest = marker.get("binding_sha256")
            if not isinstance(digest, str) or native.SHA256.fullmatch(digest) is None:
                raise ValueError("OCRV resume binding provenance is not a SHA256")
            observer = SimpleNamespace(binding={}, digest=digest, endpoint=lambda _: dict(endpoint),
                _source_sha256=RoleHost._source_sha256)
        ocrv_resume_identity(child, observer, Envelope.from_dict(envelope))
        if sha256_file(child / "ocrv-request.json") != original_start["native_request_sha256"]:
            raise ValueError("OCRV resume changed its original native request")
        binding = _object(current / "ocrv-session-binding.json")
        if binding.get("session_id") != marker["resume_session_id"]:
            raise ValueError("OCRV resume changed its original Session")
        require_stopped_ocrv(current / "native-start.received.json", parent_start)
        path = child / "started.json"
        metadata = {"invocation_id": child.name, "native_start_path": str(path), "native_start_sha256": None}
        if not path.is_file():
            if any((child / name).exists() for name in ("completed.json", "failed.json", "review-corrections")):
                raise ValueError("OCRV resume without a start cannot have a terminal or successor")
            return OcrvResumeObservation(child, None, metadata)
        start = validate_native_start(path, adapter=endpoint["adapter"], run_id=envelope["run_id"],
            cell_id=envelope["cell_id"], message_id=envelope["message_id"], request_sha256=envelope["payload_sha256"],
            native_request_sha256=original_start["native_request_sha256"])
        source = _object(child / "ocrv-native-source.json")
        if (start["native_task"]["id"] != child.name or validate_native_start(child / "native-start.received.json") != start
            or source.get("resume_session_id") != marker["resume_session_id"]):
            raise ValueError("OCRV resume start changed its actual native invocation")
        metadata["native_start_sha256"] = sha256_file(path)
        selected = OcrvResumeObservation(child, path, metadata)
        current, parent_start = child, start
