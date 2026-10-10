"""Exact native JSONL facts, with no models or private payload exposure."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from slk_transport.native_activity import NativeActivityError, inspect_native_activity, process_creation_time, validate_native_start
from slk_transport.adapters.ocrv import _await_native_start, _native_start_context
from slk_transport.contracts import Endpoint, Envelope
from slk_transport.evidence import Attempt
from test_contracts import endpoint_value, envelope_value


def write(path, value):
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def fixture(tmp_path):
    repository = tmp_path / "repo"
    repository.mkdir()
    sessions = tmp_path / "sessions"
    sessions.mkdir()
    request = write(tmp_path / "ocrv-request.json", {"repository": str(repository),
        "candidate": {"kind": "commit", "commit": "c" * 40}})
    digest = hashlib.sha256(request.read_bytes()).hexdigest()
    endpoint, envelope = Endpoint.from_dict(endpoint_value()), Envelope.from_dict(envelope_value())
    path = Path(__file__).resolve().parents[2] / "integrations/ocrv/slk_checker_adapter.py"
    spec = importlib.util.spec_from_file_location("original_ocrv_publisher", path)
    publisher = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(publisher)
    receipt = tmp_path / "native-start.received.json"
    publisher._publish_native_start(receipt, _native_start_context(endpoint, envelope, digest),
                                    "original-invocation", os.getpid())
    child_start = _await_native_start(SimpleNamespace(poll=lambda: None), receipt, endpoint, envelope, digest, 1)
    started = Attempt(tmp_path).write_json_once("started.json", child_start)
    start = validate_native_start(started)
    marker = "SLK_NATIVE_INVOCATION=" + start["native_task"]["id"] + ";REQUEST_SHA256=" + digest
    background = tmp_path / "background.md"
    background.write_text(marker + "\noriginal background", encoding="utf-8")
    source = {"schema_version": "slk.ocrv-native-source/v1", "run_id": start["run_id"],
        "cell_id": start["cell_id"], "message_id": start["message_id"], "invocation_id": start["native_task"]["id"],
        "native_start_sha256": hashlib.sha256(receipt.read_bytes()).hexdigest(),
        "request_path": str(request), "background_path": str(background),
        "background_sha256": hashlib.sha256(background.read_bytes()).hexdigest(), "marker": marker,
        "session_directory": str(sessions), "prior_sessions": [], "resume_session_id": None}
    write(tmp_path / "ocrv-native-source.json", source)
    header = {"type": "session_start", "sessionId": "native-session-a", "uuid": "header-a",
        "timestamp": "2026-10-01T00:00:01Z", "cwd": str(repository), "diffCommit": "c" * 40,
        "llmSource": "provider:dashscope-tokenplan", "model": "qwen3.8-max"}
    request_record = {"type": "llm_request", "sessionId": "native-session-a", "uuid": "request-a",
        "timestamp": "2026-10-01T00:00:02Z", "messages": [{"role": "user", "content": marker}]}
    tool = {"type": "tool_call", "sessionId": "native-session-a", "uuid": "tool-a",
        "timestamp": "2026-10-01T00:01:00Z", "tool_name": "file_read", "ok": True,
        "duration_ms": 7, "arguments": "PRIVATE_ARGUMENTS", "result": "PRIVATE_RESULT"}
    session = sessions / "native-session-a.jsonl"
    session.write_text("".join(json.dumps(row) + "\n" for row in (header, request_record, tool)), encoding="utf-8")
    return started, source, session, header, request_record, tool


def inspect(started):
    return inspect_native_activity(started, process_probe=lambda *_: {"exists": True, "identity_matches": True})


@pytest.mark.parametrize("damage", [None, "receipt-bytes", "receipt-identity", "started-identity", "source-hash"])
def test_original_receipt_transport_serialization_and_reader_preserve_both_proofs(tmp_path, damage):
    started, source, session, header, request, tool = fixture(tmp_path)
    receipt = started.with_name("native-start.received.json")
    assert receipt.read_bytes() != started.read_bytes()  # real producer order vs Attempt sorted publication
    assert validate_native_start(receipt) == validate_native_start(started)
    if damage == "receipt-bytes":
        receipt.write_bytes(receipt.read_bytes() + b"\n")
    elif damage in {"receipt-identity", "started-identity"}:
        path = receipt if damage == "receipt-identity" else started
        value = validate_native_start(path)
        value["process"]["pid"] += 1
        write(path, value)
        if damage == "receipt-identity":
            source["native_start_sha256"] = hashlib.sha256(receipt.read_bytes()).hexdigest()
            write(started.with_name("ocrv-native-source.json"), source)
    elif damage == "source-hash":
        source["native_start_sha256"] = hashlib.sha256(started.read_bytes()).hexdigest()
        write(started.with_name("ocrv-native-source.json"), source)
    result = inspect(started)
    if damage is None:
        assert result["error"] == "OCRV_SESSION_STATUS_UNAVAILABLE"
        assert result["last_event"]["session_id"] == "native-session-a"
    else:
        assert result["error"] == "OCRV_NATIVE_SESSION_UNPROVEN"
        assert result["last_event"] is None


def test_exact_marker_exposes_native_tool_even_when_wrapper_stays_sequence_zero(tmp_path):
    started, source, session, header, request, tool = fixture(tmp_path)
    first = inspect(started)
    assert first["last_event"]["session_id"] == "native-session-a"
    assert first["last_event"]["tool_name"] == "file_read"
    assert first["last_event"]["observed_at"] == tool["timestamp"]
    assert first["status"] == "UNKNOWN"  # no native live driver status exists in JSONL
    assert first["error"] == "OCRV_SESSION_STATUS_UNAVAILABLE"
    binding = (started.parent / "ocrv-session-binding.json").read_bytes()
    with session.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps({**tool, "uuid": "tool-b", "timestamp": "2026-10-01T00:02:00Z"}) + "\n")
    second = inspect(started)
    assert second["last_event"]["sequence"] > first["last_event"]["sequence"]
    assert (started.parent / "ocrv-session-binding.json").read_bytes() == binding
    assert "PRIVATE" not in json.dumps(first) + binding.decode()


@pytest.mark.parametrize("damage", ["missing-marker", "wrong-provider", "wrong-model", "wrong-commit", "ambiguous"])
def test_session_identity_never_comes_from_latest_time_or_same_cwd(tmp_path, damage):
    started, source, session, header, request, tool = fixture(tmp_path)
    if damage == "missing-marker": request["messages"] = [{"content": "unrelated input"}]
    if damage == "wrong-provider": header["llmSource"] = "provider:other"
    if damage == "wrong-model": header["model"] = "other-model"
    if damage == "wrong-commit": header["diffCommit"] = "d" * 40
    session.write_text("".join(json.dumps(row) + "\n" for row in (header, request, tool)), encoding="utf-8")
    if damage == "ambiguous":
        (session.parent / "second-session.jsonl").write_text(session.read_text().replace("native-session-a", "second-session"))
    result = inspect(started)
    assert result["status"] == "UNKNOWN"
    assert result["error"] == "OCRV_NATIVE_SESSION_UNPROVEN"
    assert not (started.parent / "ocrv-session-binding.json").exists()


def test_large_private_rows_are_not_an_observation_size_gate_and_bound_session_end_is_factual(tmp_path):
    started, source, session, header, request, tool = fixture(tmp_path)
    with session.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps({"type": "llm_response", "sessionId": "native-session-a",
            "reasoning_content": "PRIVATE" * 1800000}) + "\n")
        stream.write(json.dumps({"type": "session_end", "sessionId": "native-session-a", "uuid": "end-a",
            "timestamp": "2026-10-01T00:30:00Z", "duration_seconds": 1800}) + "\n")
    result = inspect(started)
    assert session.stat().st_size > 10 * 1024 * 1024
    assert result["status"] == "COMPLETED_WITHOUT_TERMINAL"
    assert result["last_event"]["kind"] == "OCRV_SESSION_END"
    assert "PRIVATE" not in json.dumps(result)


def test_resumed_run_fresh_session_id_is_not_conflicted_by_closed_parent_session(tmp_path):
    started, source, session, header, request, tool = fixture(tmp_path)
    parent_id = "closed-parent-session"
    parent = session.with_name(parent_id + ".jsonl")
    old_header = {**header, "sessionId": parent_id, "uuid": "parent-header", "timestamp": "2026-09-30T00:00:01Z"}
    old_end = {"type": "session_end", "sessionId": parent_id, "uuid": "parent-end",
               "timestamp": "2026-09-30T00:30:00Z", "duration_seconds": 1800}
    parent.write_text("".join(json.dumps(row) + "\n" for row in (old_header, old_end)), encoding="utf-8")
    source.update(prior_sessions=[parent.name], resume_session_id=parent_id)
    write(started.with_name("ocrv-native-source.json"), source)
    # Native 1.12.13 opens a new Session file even when resuming a closed parent.
    header["resumedFrom"] = parent_id
    end = {**old_end, "sessionId": header["sessionId"], "uuid": "current-end", "timestamp": "2026-10-01T00:30:00Z"}
    session.write_text("".join(json.dumps(row) + "\n" for row in (header, request, tool, end)), encoding="utf-8")
    result = inspect(started)
    assert result["status"] == "COMPLETED_WITHOUT_TERMINAL"
    assert result["last_event"]["session_id"] == header["sessionId"]
    assert result["error"] is None
    binding = json.loads(started.with_name("ocrv-session-binding.json").read_text(encoding="utf-8"))
    assert binding["session_id"] == header["sessionId"]
    assert binding["header_sha256"] == hashlib.sha256(session.read_bytes().splitlines(keepends=True)[0]).hexdigest()


@pytest.mark.parametrize("suffix", ["tool_call", "session_end", "session_start", "private", "incomplete"])
def test_native_end_conflicts_with_later_public_actions_but_not_private_or_incomplete_appends(tmp_path, suffix):
    started, source, session, header, request, tool = fixture(tmp_path)
    end = {"type": "session_end", "sessionId": "native-session-a", "uuid": "original-end",
           "timestamp": "2026-10-01T00:30:00Z", "duration_seconds": 1800}
    with session.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(end) + "\n")
    first = inspect(started)
    assert first["status"] == "COMPLETED_WITHOUT_TERMINAL"
    binding_path = started.with_name("ocrv-session-binding.json")
    binding = binding_path.read_bytes()
    row = {**{"tool_call": tool, "session_end": end, "session_start": header}.get(suffix, tool),
           "uuid": "later-action", "timestamp": "2026-10-01T00:31:00Z"}
    if suffix == "private":
        row = {"type": "llm_response", "sessionId": "native-session-a", "reasoning_content": "PRIVATE_NATIVE_TEXT"}
    with session.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(row) + ("" if suffix == "incomplete" else "\n"))
    result = inspect(started)
    assert binding_path.read_bytes() == binding
    assert "PRIVATE" not in json.dumps(result)
    if suffix in {"private", "incomplete"}:
        assert result["status"] == "COMPLETED_WITHOUT_TERMINAL"
        assert result["last_event"] == first["last_event"]
    else:
        assert result["status"] == "UNKNOWN"
        assert result["error"] == "OCRV_SESSION_EVENT_AFTER_END"
        assert result["last_event"]["observed_at"] == row["timestamp"]
        assert [item["kind"] for item in result["last_event"]["tail"]] == ["OCRV_SESSION_END", result["last_event"]["kind"]]


@pytest.mark.parametrize("damage", ["header", "marker", "source"])
def test_bound_header_and_input_record_cannot_be_replaced_by_mutable_file_hash(tmp_path, damage):
    started, source, session, header, request, tool = fixture(tmp_path)
    assert inspect(started)["last_event"]["session_id"] == "native-session-a"
    if damage == "header": header["model"] = "other-model"
    if damage == "marker": request["uuid"] = "replacement-request"
    if damage == "source":
        source["invocation_id"] = "another-invocation"
        write(started.parent / "ocrv-native-source.json", source)
    session.write_text("".join(json.dumps(row) + "\n" for row in (header, request, tool)), encoding="utf-8")
    result = inspect(started)
    assert result["status"] == "UNKNOWN"
    assert result["error"] == "OCRV_NATIVE_SESSION_UNPROVEN"


@pytest.mark.parametrize("damage", [None, "wrong-pid", "wrong-creation", "wrong-invocation"])
@pytest.mark.parametrize("launcher_state", ["alive", "dead", "unavailable"])
def test_only_exact_native_process_and_marker_session_prove_execution_not_progress(tmp_path, damage, launcher_state):
    started, source, session, header, request, tool = fixture(tmp_path)
    start = validate_native_start(started)
    index = write(tmp_path / "evidence-index.json", {"native_task_id": start["native_task"]["id"],
        **{key: start[key] for key in ("run_id", "cell_id", "message_id", "native_request_sha256")}})
    value = {"schema_version": "slk.ocrv-native-process/v1", "native_task_id": start["native_task"]["id"],
        **{key: start[key] for key in ("run_id", "cell_id", "message_id", "native_request_sha256")},
        "native_start_sha256": source["native_start_sha256"], "index_path": str(index),
        "index_sha256": hashlib.sha256(index.read_bytes()).hexdigest(),
        "launcher_process": start["process"], "process": {"pid": os.getpid(), "creation_time": process_creation_time(os.getpid())}}
    if damage == "wrong-pid": value["process"]["pid"] = 2147483647
    if damage == "wrong-creation": value["process"]["creation_time"] = "different-process"
    if damage == "wrong-invocation": value["native_task_id"] = "different-invocation"
    write(tmp_path / "ocrv-native-process.json", value)
    def launcher_probe(*_):
        if launcher_state == "unavailable":
            raise NativeActivityError("launcher query unavailable")
        return {"exists": launcher_state == "alive", "identity_matches": launcher_state == "alive"}

    result = inspect_native_activity(started, process_probe=launcher_probe)
    assert result["last_event"]["session_id"] == "native-session-a"
    assert result["last_event"]["observed_at"] == "2026-10-01T00:01:00Z"
    assert result["status"] == ("ACTIVE" if damage is None else "UNKNOWN")
