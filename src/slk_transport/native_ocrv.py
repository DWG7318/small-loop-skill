"""Read the exact original OCRV Session; never publish private native payloads."""
from __future__ import annotations

import hashlib
import json
import os
import re
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
                if (os.path.normcase(str(Path(row["cwd"]).resolve())) != os.path.normcase(str(Path(request["repository"]).resolve()))
                    or row.get("llmSource") != "provider:dashscope-tokenplan" or row.get("model") != "qwen3.8-max"):
                    return None
                candidate = request["candidate"]
                if candidate["kind"] == "commit" and row.get("diffCommit") != candidate["commit"]:
                    return None
                if candidate["kind"] == "range" and (row.get("diffFrom"), row.get("diffTo")) != (candidate["from"], candidate["to"]):
                    return None
                header = {"session_id": row["sessionId"], "header_sha256": hashlib.sha256(raw).hexdigest()}
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


def inspect_ocrv_session(started_path: Path, start: Mapping[str, Any]) -> Mapping[str, Any]:
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
