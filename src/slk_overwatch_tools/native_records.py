"""Read caller-selected Codex rollouts; never discover, write, attest or refresh them.

The caller authenticates the absolute source and current role/execution binding.
Private Codex JSONL is not a stable API or cryptographic platform attestation.
Only hashes and selected status metadata are returned, never record bodies.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

CALL_ID = re.compile(r"^call_[A-Za-z0-9_]+$")


class OverwatcherSubagentError(ValueError):
    """An exact native locator or its original status sample is unproved."""


def native_text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise OverwatcherSubagentError(f"{label} must be one canonical non-empty string")
    return value


def native_object(value: Any) -> dict[str, Any]:
    def closed_pairs(pairs):
        result = {}
        for key, item in pairs:
            if key in result:
                raise OverwatcherSubagentError("duplicate JSON object key in native evidence")
            result[key] = item
        return result

    if isinstance(value, (str, bytes)):
        value = json.loads(value, object_pairs_hook=closed_pairs)
    if not isinstance(value, dict):
        raise OverwatcherSubagentError("native evidence must be a JSON object")
    return value


def native_timestamp(value: Any) -> str:
    value = native_text(value, "native timestamp")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise OverwatcherSubagentError("native timestamp requires a timezone")
    return value


def native_execution(value: Any) -> tuple[str, str]:
    value = native_text(value, "native execution")
    kind, _, call_id = value.partition(":")
    if kind not in {"codex-subagent-spawn", "codex-subagent-followup"} or not CALL_ID.fullmatch(call_id):
        raise OverwatcherSubagentError("native execution must locate one real activation call")
    return kind, call_id


def spawn_call_id(value: Mapping[str, Any]) -> str:
    return value.get("spawn_call_id", native_execution(value["native_execution_id"])[1])


def native_source_paths(request: Mapping[str, Any]) -> list[str]:
    """Return explicit sources in caller-supplied order, never discover a file."""
    if ("native_source_path" in request) == ("native_source_paths" in request):
        raise OverwatcherSubagentError("select exactly one native source form")
    sources = request.get("native_source_paths", [request.get("native_source_path")])
    if not isinstance(sources, list) or not sources:
        raise OverwatcherSubagentError("native sources must be a non-empty explicit list")
    resolved = []
    for source in sources:
        path = Path(native_text(source, "native source path"))
        if not path.is_absolute():
            raise OverwatcherSubagentError("native source must be absolute")
        resolved.append(path.resolve())
    if len(set(resolved)) != len(resolved):
        raise OverwatcherSubagentError("native source paths must be unique")
    return sources


def _source_records(request: Mapping[str, Any], metadata: list):
    """Stream original records with real locations; do not create a merged rollout."""
    sequence = 0
    previous_time = None
    multiple = "native_source_paths" in request
    parent_id = request["native_address"]["parent"]["session_id"]
    for source in native_source_paths(request):
        metas = []
        with Path(source).open("rb") as stream:
            for local_line, raw in enumerate(stream, 1):
                sequence += 1
                raw = raw.rstrip(b"\r\n")
                record = native_object(raw)
                digest = hashlib.sha256(raw).hexdigest()
                location = {"path": source, "line": local_line, "sha256": digest}
                payload = record.get("payload")
                if record.get("type") == "session_meta" and isinstance(payload, dict):
                    metas.append(payload.get("id"))
                    metadata.append(location)
                if multiple and record.get("type") == "response_item" and isinstance(payload, dict) and payload.get("type") in {"function_call", "function_call_output"}:
                    current_time = datetime.fromisoformat(native_timestamp(record.get("timestamp")).replace("Z", "+00:00"))
                    if previous_time is not None and current_time < previous_time:
                        raise OverwatcherSubagentError("explicit native sources are not in chronological record order")
                    previous_time = current_time
                yield sequence, record, digest, location
        if metas != [parent_id]:
            raise OverwatcherSubagentError("native source parent session identity is absent or ambiguous")


def read_codex_subagent_snapshot(request: Mapping[str, Any], original_sample_id: str | None = None) -> dict[str, Any]:
    """Parse exact sources once; never search by name, latest file or child UUID."""
    kind, activation_id = native_execution(request["native_execution_id"])
    spawn_id = spawn_call_id(request)
    followup = kind == "codex-subagent-followup"
    previous_id = native_execution(request["previous_native_execution_id"])[1] if followup else spawn_id
    selected_activation_ids = {spawn_id, activation_id, previous_id}
    child = request["native_address"]["agent_id"]
    calls: dict[str, list] = {}
    outputs: dict[str, list] = {}
    call_counts: dict[str, int] = {}
    output_counts: dict[str, int] = {}
    target_queries: dict[str, int] = {}
    activation_queries: dict[str, int] = {}
    other_spawns: dict[str, list] = {}
    successful_spawns: dict[str, list] = {}
    child_links = []
    source_metadata = []
    multiple = "native_source_paths" in request

    def covers_child(payload):
        if payload.get("namespace") != "collaboration" or not isinstance(payload.get("arguments"), str):
            raise OverwatcherSubagentError("native list query shape is unsupported")
        arguments = native_object(payload["arguments"])
        if set(arguments) - {"path_prefix"}:
            raise OverwatcherSubagentError("native list query is unsupported")
        prefix = arguments.get("path_prefix")
        if "path_prefix" in arguments and (not isinstance(prefix, str)
            or not re.fullmatch(r"/root(?:/[a-z0-9_]+)*", prefix)):
            raise OverwatcherSubagentError("native list filter shape is unsupported")
        return prefix is None or child == prefix or child.startswith(prefix + "/")

    def targets_child(payload):
        if payload.get("namespace") != "collaboration" or not isinstance(payload.get("arguments"), str):
            raise OverwatcherSubagentError("native followup query shape is unsupported")
        target = native_object(payload["arguments"]).get("target")
        if not isinstance(target, str) or not re.fullmatch(r"(?:/root(?:/[a-z0-9_]+)+|[a-z0-9_]+)", target):
            raise OverwatcherSubagentError("native followup target is unsupported")
        return target in {child, child.rsplit("/", 1)[-1]}

    # Keep only tool records in memory. Their raw bytes remain private, and only
    # per-record hashes leave this reader (not a frozen hash of the growing file).
    for line_number, record, digest, location in _source_records(request, source_metadata):
        record_type = native_text(record.get("type"), "native record type")
        payload = record.get("payload")
        if not isinstance(payload, dict):
            raise OverwatcherSubagentError("native record payload must be an object")
        if record_type == "event_msg" and "child_source_path" in request:
            item = payload.get("item")
            if (payload.get("type") == "item_completed" and isinstance(item, dict)
                and item.get("type") == "SubAgentActivity" and item.get("id") == spawn_id):
                child_links.append((line_number, record, digest, location))
        if record_type != "response_item":
            continue
        payload_type = native_text(payload.get("type"), "native response type")
        if payload_type not in {"function_call", "function_call_output"}:
            continue
        # Desktop injects cross-thread App receipts without an agent tool call.
        # They cannot participate in collaboration call/output pairing.
        if (payload_type == "function_call_output" and "call_id" not in payload
            and payload.get("namespace") == "codex_app"
            and payload.get("name") == "send_message_to_thread"):
            native_text(payload.get("id"), "native App receipt id")
            if not isinstance(payload.get("output"), str):
                raise OverwatcherSubagentError("native App receipt output must be text")
            continue
        call_id = native_text(payload.get("call_id"), "native function call_id")
        if payload_type == "function_call":
            native_text(payload.get("name"), "native function name")
            if "arguments" not in payload:
                raise OverwatcherSubagentError("native function arguments field is missing")
        elif "output" not in payload:
            raise OverwatcherSubagentError("native function output field is missing")
        counts = call_counts if payload["type"] == "function_call" else output_counts
        counts[call_id] = counts.get(call_id, 0) + 1
        if call_id != spawn_id and payload_type == "function_call" and payload.get("name") == "spawn_agent" and payload.get("namespace") == "collaboration":
            try:
                if isinstance(payload["arguments"], str) and native_object(payload["arguments"]).get("task_name") == child.rsplit("/", 1)[-1]:
                    other_spawns.setdefault(call_id, []).append((line_number, record.get("timestamp")))
            except (ValueError, TypeError):
                pass  # A failed/unknown spawn is not positive replacement evidence.
        if payload_type == "function_call_output" and call_id in other_spawns:
            try:
                if isinstance(payload["output"], str) and native_object(payload["output"]) == {"task_name": child}:
                    successful_spawns.setdefault(call_id, []).append((line_number, record.get("timestamp")))
            except (ValueError, TypeError):
                pass
        if payload["type"] == "function_call":
            if payload.get("name") == "followup_task" and spawn_id in outputs:
                try:
                    targeted = targets_child(payload)
                except (ValueError, TypeError):
                    targeted = True  # Unknown scope cannot prove absence of a new activation.
                if targeted:
                    activation_queries[call_id] = line_number
            if call_id not in selected_activation_ids:
                if payload.get("name") != "list_agents" or spawn_id not in outputs:
                    continue
                try:
                    covered = covers_child(payload)
                except (ValueError, TypeError):
                    # Scope cannot be established. Keep only its candidate
                    # position: latest/frozen selection must fail, while a
                    # later valid target query may supersede this failure.
                    target_queries[call_id] = line_number
                    continue
                if not covered:
                    continue
                target_queries[call_id] = line_number
        elif call_id not in selected_activation_ids and call_id not in calls:
            continue
        entry = (line_number, record, digest, location)
        target = calls if payload["type"] == "function_call" else outputs
        target.setdefault(call_id, []).append(entry)
    parent = request["native_address"]["parent"]

    def pair(call_id: str, name: str):
        if not CALL_ID.fullmatch(call_id):
            raise OverwatcherSubagentError("selected native call_id is invalid")
        query = calls.get(call_id, [])
        reply = outputs.get(call_id, [])
        if (call_counts.get(call_id) != 1 or output_counts.get(call_id) != 1
            or len(query) != 1 or len(reply) != 1 or query[0][0] >= reply[0][0]):
            raise OverwatcherSubagentError("native call/output pairing is absent or ambiguous")
        payload = query[0][1]["payload"]
        if payload.get("namespace") != "collaboration" or payload.get("name") != name:
            raise OverwatcherSubagentError("native tool namespace or name does not match")
        if not isinstance(payload.get("arguments"), str) or not isinstance(reply[0][1]["payload"].get("output"), str):
            raise OverwatcherSubagentError("native call/output encoding is unsupported")
        query_time = native_timestamp(query[0][1].get("timestamp"))
        reply_time = native_timestamp(reply[0][1].get("timestamp"))
        if datetime.fromisoformat(query_time.replace("Z", "+00:00")) > datetime.fromisoformat(reply_time.replace("Z", "+00:00")):
            raise OverwatcherSubagentError("native output timestamp precedes its query")
        output = reply[0][1]["payload"]["output"]
        if name == "followup_task":
            if output != "" or not targets_child(payload):
                raise OverwatcherSubagentError("native followup is not this parent's exact child return")
        else:
            output = native_object(output)
        return query[0], reply[0], native_object(payload.get("arguments")), output

    spawn, spawned, arguments, output = pair(spawn_id, "spawn_agent")
    task_name = arguments.get("task_name")
    if (not isinstance(task_name, str) or not re.fullmatch(r"[a-z0-9_]+", task_name)
        or child.rsplit("/", 1)[-1] != task_name or set(output) != {"task_name"} or output["task_name"] != child):
        raise OverwatcherSubagentError("native spawn is not this parent's exact child")
    for call_id, replies in successful_spawns.items():
        queries = other_spawns[call_id]
        if call_counts[call_id] == output_counts[call_id] == len(queries) == len(replies) == 1:
            query, reply = queries[0], replies[0]
            if (query[0] < reply[0] and reply[0] > spawned[0] and CALL_ID.fullmatch(call_id)
                and datetime.fromisoformat(native_timestamp(query[1]).replace("Z", "+00:00")) <= datetime.fromisoformat(native_timestamp(reply[1]).replace("Z", "+00:00"))):
                raise OverwatcherSubagentError("a later successful spawn reused this child path; use its new spawn identity")
    activation, activated = spawn, spawned
    lifecycle = {}
    record_sources = {"spawn_call": spawn[3], "spawn_output": spawned[3]}
    if followup:
        activation, activated, _, _ = pair(activation_id, "followup_task")
        previous_kind, _ = native_execution(request["previous_native_execution_id"])
        previous, previous_output, _, _ = pair(previous_id, "spawn_agent" if previous_kind == "codex-subagent-spawn" else "followup_task")
        if previous_kind == "codex-subagent-followup" and (
            previous[0] <= spawned[0]
            or datetime.fromisoformat(previous[1]["timestamp"].replace("Z", "+00:00")) < datetime.fromisoformat(spawned[1]["timestamp"].replace("Z", "+00:00"))
        ):
            raise OverwatcherSubagentError("previous followup does not belong to this original spawn")
        if previous_output[0] >= activation[0]:
            raise OverwatcherSubagentError("previous native execution does not precede this activation")
        for prefix, query, reply in (("activation", activation, activated), ("previous_activation", previous, previous_output)):
            lifecycle.update({f"{prefix}_call_sha256": query[2], f"{prefix}_output_sha256": reply[2],
                              f"{prefix}_query_timestamp": query[1]["timestamp"], f"{prefix}_output_timestamp": reply[1]["timestamp"]})
            record_sources.update({f"{prefix}_call": query[3], f"{prefix}_output": reply[3]})
    if any(position > activation[0] or calls[previous_id][0][0] < position < activation[0]
           for call_id, position in activation_queries.items() if call_id not in {activation_id, previous_id}):
        raise OverwatcherSubagentError("another native activation prevents exact execution attribution")
    if not target_queries:
        raise OverwatcherSubagentError("native post-spawn child sample is unavailable")
    post_queries = {key: position for key, position in target_queries.items() if position > activated[0]}
    if not post_queries:
        raise OverwatcherSubagentError("native post-activation query is unavailable")
    latest_id = max(post_queries, key=post_queries.get)
    selected = {latest_id}
    if original_sample_id is not None:
        if original_sample_id not in target_queries:
            raise OverwatcherSubagentError("frozen original native sample is missing")
        selected.add(original_sample_id)
    if followup:
        if request["pre_activation_sample_call_id"] not in target_queries:
            raise OverwatcherSubagentError("pre-activation query does not cover this child")
        selected.add(request["pre_activation_sample_call_id"])
    samples = {}
    for call_id in selected:
        query, reply, arguments, output = pair(call_id, "list_agents")
        if set(output) != {"agents"} or not isinstance(output["agents"], list):
            raise OverwatcherSubagentError("native list output shape is unsupported")
        matching = [agent for agent in output["agents"] if isinstance(agent, dict) and agent.get("agent_name") == child]
        if len(matching) != 1 or set(matching[0]) != {"agent_name", "agent_status"}:
            raise OverwatcherSubagentError("native child status is absent or ambiguous")
        status = matching[0]["agent_status"]
        if status == "running":
            status = "RUNNING"
        elif isinstance(status, dict) and set(status) == {"completed"} and isinstance(status["completed"], str):
            status = "COMPLETED"
        else:
            raise OverwatcherSubagentError("native child status shape is unsupported")
        samples[call_id] = {
            "sample_call_id": call_id, "sample_call_sha256": query[2], "sample_output_sha256": reply[2],
            "sample_query_timestamp": query[1]["timestamp"], "sample_output_timestamp": reply[1]["timestamp"],
            "query_sequence": query[0], "sequence": reply[0], "agent_status": status,
        }
        if multiple:
            samples[call_id]["record_sources"] = {"sample_call": query[3], "sample_output": reply[3]}
    if followup:
        pre = samples[request["pre_activation_sample_call_id"]]
        if (pre["agent_status"] != "COMPLETED" or pre["query_sequence"] <= previous_output[0]
            or pre["sequence"] >= activation[0]
            or request["pre_activation_sample_call_id"] != max(
                (key for key, position in target_queries.items() if previous_output[0] < position < activation[0]),
                key=target_queries.get, default=None)):
            raise OverwatcherSubagentError("followup requires the latest completed sample of the exact previous execution")
        activation_time = datetime.fromisoformat(activation[1]["timestamp"].replace("Z", "+00:00"))
        for field in ("sample_query_timestamp", "sample_output_timestamp"):
            sample_time = datetime.fromisoformat(pre[field].replace("Z", "+00:00"))
            age = (activation_time - sample_time).total_seconds()
            if not 0 <= age <= 300 or sample_time < datetime.fromisoformat(previous_output[1]["timestamp"].replace("Z", "+00:00")):
                raise OverwatcherSubagentError("pre-activation native sample was not current at activation")
        lifecycle.update({"pre_activation_" + key: pre[key] for key in (
            "sample_call_sha256", "sample_output_sha256", "sample_query_timestamp", "sample_output_timestamp")})
        if multiple:
            record_sources.update({"pre_activation_" + key: value for key, value in pre["record_sources"].items()})
    for call_id in selected - ({request["pre_activation_sample_call_id"]} if followup else set()):
        if samples[call_id]["query_sequence"] <= activated[0]:
            raise OverwatcherSubagentError("native running sample must be queried after the activation returned")
        if datetime.fromisoformat(samples[call_id]["sample_query_timestamp"].replace("Z", "+00:00")) < datetime.fromisoformat(activated[1]["timestamp"].replace("Z", "+00:00")):
            raise OverwatcherSubagentError("native running sample timestamp precedes activation return")
    latest = samples[latest_id]
    child_evidence = {}
    if "child_source_path" in request:
        if len(child_links) != 1:
            raise OverwatcherSubagentError("native child UUID linkage is absent or ambiguous")
        link = child_links[0]
        payload, item = link[1]["payload"], link[1]["payload"]["item"]
        if (payload.get("thread_id") != parent["session_id"] or item.get("kind") != "started"
            or item.get("agent_path") != child or link[0] <= spawn[0]
            or datetime.fromisoformat(native_timestamp(link[1]["timestamp"]).replace("Z", "+00:00"))
               < datetime.fromisoformat(spawn[1]["timestamp"].replace("Z", "+00:00"))):
            raise OverwatcherSubagentError("native child UUID linkage changed exact spawn/parent/path")
        child_evidence = ({"child_session_id": item.get("agent_thread_id")} if latest["agent_status"] == "COMPLETED"
                          else _read_child_sample(request, item.get("agent_thread_id"), activated[1]["timestamp"]))
        child_evidence["child_link_sha256"] = link[2]
        record_sources["child_link"] = link[3]
    provenance = {}
    if multiple:
        provenance = {"source_metadata": source_metadata,
                      "record_sources": {**record_sources, **latest["record_sources"]}}
    return {
        "spawn_call_id": spawn_id, "spawn_call_sha256": spawn[2], "spawn_output_sha256": spawned[2],
        "spawn_query_timestamp": spawn[1]["timestamp"], "spawn_output_timestamp": spawned[1]["timestamp"],
        "samples": samples, **lifecycle, **latest, **child_evidence, **provenance,
    }


def _read_child_sample(request: Mapping[str, Any], child_id: Any, activated_at: str) -> dict[str, Any]:
    """Read only the explicitly bound child source; metadata joins it to the parent spawn."""
    if not isinstance(child_id, str) or not re.fullmatch(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", child_id):
        raise OverwatcherSubagentError("native child UUID is invalid")
    source = Path(request["child_source_path"])
    if not re.fullmatch(r"rollout-\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}-" + re.escape(child_id)
                        + r"(?:_[0-9a-f-]+)?\.jsonl", source.name):
        raise OverwatcherSubagentError("native child source does not locate the exact linked UUID")
    child = request["native_address"]["agent_id"]
    parent_id = request["native_address"]["parent"]["session_id"]
    metas, queries, calls, outputs = [], {}, {}, {}
    with source.open("rb") as stream:
        for line_number, raw in enumerate(stream, 1):
            raw = raw.rstrip(b"\r\n")
            record = native_object(raw)
            payload = record.get("payload")
            if not isinstance(payload, dict):
                raise OverwatcherSubagentError("native child payload is malformed")
            entry = (line_number, record, hashlib.sha256(raw).hexdigest())
            if record.get("type") == "session_meta":
                metas.append(entry)
            if record.get("type") != "response_item" or payload.get("type") not in {"function_call", "function_call_output"}:
                continue
            call_id = payload.get("call_id")
            if call_id is None and payload.get("namespace") == "codex_app" and payload.get("name") == "send_message_to_thread":
                continue
            if not isinstance(call_id, str) or not CALL_ID.fullmatch(call_id):
                raise OverwatcherSubagentError("native child call identity is invalid")
            target = calls if payload["type"] == "function_call" else outputs
            target.setdefault(call_id, []).append(entry)
            if payload["type"] == "function_call" and payload.get("name") == "list_agents":
                if payload.get("namespace") != "collaboration" or not isinstance(payload.get("arguments"), str):
                    raise OverwatcherSubagentError("native child list query is unsupported")
                arguments = native_object(payload["arguments"])
                prefix = arguments.get("path_prefix")
                if set(arguments) - {"path_prefix"} or ("path_prefix" in arguments and (
                    not isinstance(prefix, str) or not re.fullmatch(r"/root(?:/[a-z0-9_]+)*", prefix))):
                    raise OverwatcherSubagentError("native child list filter is unsupported")
                if prefix is None or child == prefix or child.startswith(prefix + "/"):
                    queries[call_id] = line_number
    if len(metas) != 1:
        raise OverwatcherSubagentError("native child metadata is absent or ambiguous")
    meta = metas[0][1]["payload"]
    spawned = native_object(native_object(native_object(meta.get("source")).get("subagent")).get("thread_spawn"))
    if (meta.get("id") != child_id or meta.get("parent_thread_id") != parent_id or meta.get("agent_path") != child
        or spawned.get("parent_thread_id") != parent_id or spawned.get("agent_path") != child
        or type(spawned.get("depth")) is not int or spawned["depth"] != child.count("/") - 1):
        raise OverwatcherSubagentError("native child metadata differs from exact parent and path")
    if not queries:
        raise OverwatcherSubagentError("native child original list query is absent")
    call_id = max(queries, key=queries.get)
    query, reply = calls.get(call_id, []), outputs.get(call_id, [])
    if len(query) != 1 or len(reply) != 1 or query[0][0] >= reply[0][0] or query[0][0] <= metas[0][0]:
        raise OverwatcherSubagentError("native child original list pair is absent or ambiguous")
    query, reply = query[0], reply[0]
    query_at, reply_at = (native_timestamp(row[1].get("timestamp")) for row in (query, reply))
    def parsed(value): return datetime.fromisoformat(value.replace("Z", "+00:00"))
    if not parsed(activated_at) <= parsed(query_at) <= parsed(reply_at):
        raise OverwatcherSubagentError("native child sample does not follow exact activation")
    raw_output = reply[1]["payload"].get("output")
    if not isinstance(raw_output, str):
        raise OverwatcherSubagentError("native child list output is unsupported")
    output = native_object(raw_output)
    if set(output) != {"agents"} or not isinstance(output["agents"], list):
        raise OverwatcherSubagentError("native child list output is unsupported")
    matching = [row for row in output["agents"] if isinstance(row, dict) and row.get("agent_name") == child]
    if len(matching) != 1 or set(matching[0]) != {"agent_name", "agent_status"} or matching[0]["agent_status"] != "running":
        raise OverwatcherSubagentError("native child own running status is absent or ambiguous")
    return {"child_session_id": child_id, "child_meta_sha256": metas[0][2], "child_sample": {
        "sample_call_id": call_id, "sample_call_sha256": query[2], "sample_output_sha256": reply[2],
        "sample_query_timestamp": query_at, "sample_output_timestamp": reply_at,
        "sequence": reply[0], "agent_status": "RUNNING"}}
