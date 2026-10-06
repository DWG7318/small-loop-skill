"""Closed continuation for one consumed fresh review with exact budget-partial coverage."""

from __future__ import annotations

import copy
import json
import uuid
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from .contracts import canonical_json_sha256
from .terminal_budget import (
    REVISION_SCHEMA,
    _ocr_command,
    _read,
    _run_command,
    _sha256,
    _validate_managed_target,
)
from .terminal_budget_fresh import (
    MODEL,
    PROVIDER,
    _authorized_at,
    _command_value,
    _exact_digest,
    _exact_identifier,
    _stable_json,
    validate_fresh_review_request,
)


REQUEST_SCHEMA = "slk.ocrv-terminal-budget-fresh-partial-request/v1"
RESULT_SCHEMA = "slk.ocrv-terminal-budget-fresh-partial-result/v1"
AUTHORIZATION_SCHEMA = "slk.owner-terminal-budget-fresh-partial-authorization/v1"
SOURCE_CONSUMPTION_SCHEMA = "slk.ocrv-terminal-budget-fresh-partial-consumption/v1"
STRATEGY = "RESUME_EXACT_FRESH_PARTIAL_CHILD"
_NAMESPACE = uuid.UUID("16336df6-1d3c-5de4-a76c-eb9b687f1ba7")
_NATIVE_FILES = {
    "compatibility-lineage.json", "completed.json", "native-activity.json",
    "native-session.jsonl", "native-start.received.json", "ocrv-capacity-request.json",
    "ocrv-result.json", "ocrv-review.json", "ocrv.stderr.txt", "ocrv.stdout.txt",
    "started.json",
}
_ROOT_FILES = {"fresh-consumed.json", "result.json", "session-show.json"}
_REQUEST_FIELDS = {
    "schema_version", "strategy", "recovery_invocation_id", "fresh_request_path",
    "fresh_request_sha256", "fresh_result_sha256", "fresh_evidence_sha256",
    "parent_session_id", "parent_session_evidence_sha256", "capacity_revision",
    "ocrv_transition", "runtime_config_binding", "owner_authorization",
    "recovery_root", "result_path",
}
_AUTHORIZATION_FIELDS = {
    "schema_version", "authority", "decision", "authorization_id", "source_thread_id",
    "fresh_request_sha256", "fresh_result_sha256", "capacity_revision_sha256",
    "ocrv_transition_sha256", "runtime_config_binding_sha256", "occurred_at",
}
_FRESH_RESULT_FIELDS = {
    "schema_version", "method_version", "status", "run_id", "cell_id", "attempt",
    "candidate_message_id", "checker_role_instance_id", "checker_endpoint_version",
    "recovery_invocation_id", "request_sha256", "capacity_revision_sha256",
    "source_rejection_sha256", "compatibility_authorization_sha256",
    "source_d1_incomplete_event_id", "d1_verdict", "d1_event_type",
    "corrected_d1_event_id", "suffix_mode", "suffix_request_path", "suffix_result_path",
    "suffix_status", "parent_session_id", "child_session_id", "native_attempt_path",
    "native_result_path",
}

CommandRunner = Callable[[list[str]], Any]
_PROVIDER_THINKING_FIELDS = {"thinking", "reasoning", "analysis"}


def _without_provider_thinking(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            key: _without_provider_thinking(item)
            for key, item in value.items()
            if key not in _PROVIDER_THINKING_FIELDS
        }
    if isinstance(value, list):
        return [_without_provider_thinking(item) for item in value]
    return value


def _identities(items: object) -> set[tuple[str, str, str]]:
    if not isinstance(items, list):
        raise ValueError("fresh-partial coverage is not an object array")
    values: set[tuple[str, str, str]] = set()
    for item in items:
        if not isinstance(item, Mapping):
            raise ValueError("fresh-partial coverage item is invalid")
        identity = tuple(str(item.get(key, "")) for key in ("item_id", "path", "fingerprint"))
        if not all(identity) or len(identity[2]) != 64 or identity in values:
            raise ValueError("fresh-partial coverage identity is missing or duplicated")
        values.add(identity)
    return values


def _evidence_paths(fresh: Mapping[str, Any]) -> dict[str, Path]:
    root = Path(str(fresh["recovery_root"])).resolve()
    paths = {name: root / name for name in _ROOT_FILES}
    paths.update({f"native-attempt/{name}": root / "native-attempt" / name for name in _NATIVE_FILES})
    return paths


def _source_marker(fresh: Mapping[str, Any]) -> Path:
    return Path(str(fresh["recovery_root"])).resolve() / "fresh-partial-source-consumed.json"


def _claim_payload(request: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": SOURCE_CONSUMPTION_SCHEMA,
        "fresh_request_sha256": request["fresh_request_sha256"],
        "fresh_result_sha256": request["fresh_result_sha256"],
        "authorization_sha256": canonical_json_sha256(request["owner_authorization"]),
        "recovery_invocation_id": request["recovery_invocation_id"],
    }


def claim_fresh_partial_source(request: Mapping[str, Any]) -> Path:
    from . import worker_completion as wc

    fresh = _read(Path(str(request["fresh_request_path"])).resolve(), "fresh-review request")
    marker = _source_marker(fresh)
    try:
        with marker.open("x", encoding="utf-8") as stream:
            json.dump(_claim_payload(request), stream, sort_keys=True)
            stream.write("\n")
    except FileExistsError as exc:
        raise wc.CompletionError(
            "CHECKER_TERMINAL_BUDGET_FRESH_PARTIAL_ALREADY_CONSUMED",
            "the exact fresh partial Session already consumed its one continuation",
        ) from exc
    return marker


def _validate_partial_evidence(
    fresh: Mapping[str, Any], fresh_path: Path, source: Mapping[str, Any],
    evidence_hashes: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    paths = _evidence_paths(fresh)
    root = Path(str(fresh["recovery_root"])).resolve()
    attempt = root / "native-attempt"
    if (
        set(path.name for path in attempt.iterdir()) != _NATIVE_FILES
        or any(not path.is_file() for path in paths.values())
    ):
        raise ValueError("consumed fresh partial evidence is incomplete or ambiguous")
    hashes = {name: _sha256(path) for name, path in paths.items()}
    if evidence_hashes is not None and dict(evidence_hashes) != hashes:
        raise ValueError("consumed fresh partial evidence changed")
    outer = _read(root / "result.json", "fresh-review result")
    result = _read(attempt / "ocrv-result.json", "fresh native result")
    raw = _read(attempt / "ocrv-review.json", "fresh raw review")
    terminal = _read(attempt / "completed.json", "fresh terminal")
    start = _read(attempt / "started.json", "fresh start")
    received = _read(attempt / "native-start.received.json", "fresh received start")
    activity = _read(attempt / "native-activity.json", "fresh activity")
    lineage = _read(attempt / "compatibility-lineage.json", "fresh compatibility lineage")
    capacity = _read(attempt / "ocrv-capacity-request.json", "fresh capacity request")
    manifest = raw.get("manifest")
    coverage = manifest.get("coverage") if isinstance(manifest, Mapping) else None
    execution = manifest.get("execution") if isinstance(manifest, Mapping) else None
    input_value = manifest.get("input") if isinstance(manifest, Mapping) else None
    summary = raw.get("summary")
    tools = raw.get("tool_calls")
    selected = _identities(coverage.get("selected")) if isinstance(coverage, Mapping) else set()
    completed = _identities(coverage.get("completed")) if isinstance(coverage, Mapping) else set()
    reused = _identities(coverage.get("reused")) if isinstance(coverage, Mapping) else set()
    failed = _identities(coverage.get("failed")) if isinstance(coverage, Mapping) else set()
    comments = raw.get("comments")
    retry = raw.get("retry_report")
    retry_requests = retry.get("requests") if isinstance(retry, Mapping) else None
    cancelled = retry_requests[0] if isinstance(retry_requests, list) and len(retry_requests) == 1 else None
    cancelled_attempts = cancelled.get("attempts") if isinstance(cancelled, Mapping) else None
    completed_paths = {item[1] for item in completed}
    failed_paths = {item[1] for item in failed}
    original = _read(
        Path(str(source["native_attempt_path"])).resolve() / "ocrv-request.json",
        "original OCRV request",
    )
    expected_capacity = copy.deepcopy(original)
    expected_capacity["capacity"] = {
        **dict(original.get("capacity", {})), **source["capacity_revision"]["new"]
    }
    child_session = result.get("review", {}).get("session_id")
    expected_lineage = {
        "schema_version": "slk.ocrv-terminal-budget-fresh-compatibility-lineage/v1",
        "strategy": fresh["strategy"], "source_request_path": fresh["source_request_path"],
        "source_request_sha256": fresh["source_request_sha256"],
        "source_rejection_sha256": fresh["source_rejection_sha256"],
        "compatibility_request_path": str(fresh_path),
        "compatibility_request_sha256": _sha256(fresh_path),
        "parent_session_id": source["ocrv_session"]["session_id"],
        "child_session_id": child_session,
        "review_invocation_id": result.get("review_invocation_id"),
        "candidate_commit": source["candidate_commit"],
        "candidate_message_id": source["candidate_message_id"],
        "d1_started_event_id": source["d1_started_event_id"],
        "d1_incomplete_event_id": source["d1_incomplete_event_id"],
        "authorization_sha256": canonical_json_sha256(fresh["owner_authorization"]),
        "native_session_sha256": _sha256(attempt / "native-session.jsonl"),
        "checkpoint_reuse": False,
    }
    if (
        set(outer) != _FRESH_RESULT_FIELDS
        or outer.get("schema_version") != "slk.ocrv-terminal-budget-fresh-review-result/v1"
        or outer.get("status") != "CHECKER_D1_STILL_INCOMPLETE"
        or outer.get("d1_verdict") != "INCOMPLETE" or outer.get("d1_event_type") != "D1_INCOMPLETE"
        or outer.get("request_sha256") != _sha256(fresh_path)
        or outer.get("run_id") != source["run_id"] or outer.get("cell_id") != source["cell_id"]
        or outer.get("attempt") != source["attempt"]
        or outer.get("candidate_message_id") != source["candidate_message_id"]
        or outer.get("checker_role_instance_id") != source["checker_role_instance_id"]
        or outer.get("checker_endpoint_version") != source["checker_endpoint_version"]
        or outer.get("recovery_invocation_id") != fresh["recovery_invocation_id"]
        or outer.get("capacity_revision_sha256") != canonical_json_sha256(source["capacity_revision"])
        or outer.get("source_d1_incomplete_event_id") != source["d1_incomplete_event_id"]
        or outer.get("parent_session_id") != source["ocrv_session"]["session_id"]
        or outer.get("child_session_id") != child_session
        or Path(str(outer.get("native_attempt_path", ""))).resolve() != attempt
        or Path(str(outer.get("native_result_path", ""))).resolve() != attempt / "ocrv-result.json"
        or result.get("schema_version") != "slk.ocrv-d1-result/v1"
        or result.get("run_id") != source["run_id"] or result.get("cell_id") != source["cell_id"]
        or result.get("verdict") != "INCOMPLETE"
        or result.get("findings") != _without_provider_thinking(comments)
        or result.get("review", {}).get("status") != "partial"
        or result.get("review", {}).get("provider") != PROVIDER
        or result.get("review", {}).get("model") != MODEL
        or not isinstance(child_session, str) or not child_session
        or result.get("request_sha256") != _sha256(attempt / "ocrv-capacity-request.json")
        or raw.get("status") != "partial" or raw.get("session_id") != child_session
        or not isinstance(summary, Mapping) or summary.get("budget_exceeded") is not True
        or not isinstance(summary.get("total_tokens"), int) or summary["total_tokens"] <= 0
        or not isinstance(tools, Mapping) or tools.get("failure") != 0
        or not isinstance(retry, Mapping)
        or retry.get("schema_version") != "ocr.llm-retry-report/v1"
        or not isinstance(retry.get("total_requests"), int) or retry["total_requests"] <= 0
        or any(retry.get(name) != 0 for name in (
            "retried_requests", "total_retries", "recovered_requests", "failed_requests"
        ))
        or retry.get("cancelled_requests") != 1
        or not isinstance(cancelled, Mapping) or cancelled.get("outcome") != "cancelled"
        or cancelled.get("provider") != PROVIDER or cancelled.get("model") != MODEL
        or cancelled.get("task_type") != "memory_compression_task"
        or not isinstance(cancelled_attempts, list) or not cancelled_attempts
        or any(
            not isinstance(item, Mapping) or item.get("outcome") != "error"
            or item.get("error_class") != "cancelled" or item.get("failure_phase") != "context"
            for item in cancelled_attempts
        )
        or not isinstance(manifest, Mapping) or manifest.get("terminal_state") != "partial"
        or manifest.get("run_id") != child_session or manifest.get("operation") != "review"
        or not isinstance(input_value, Mapping)
        or input_value.get("resolved_base") != source["candidate_parent"]
        or input_value.get("resolved_head") != source["candidate_commit"]
        or input_value.get("exact_range") != f'{source["candidate_parent"]}..{source["candidate_commit"]}'
        or not isinstance(execution, Mapping)
        or execution.get("ocr_version") != source["ocrv_transition"]["target_version"]
        or execution.get("provider") != PROVIDER or execution.get("model") != MODEL
        or execution.get("rule_config_sha256") != source["ocrv_transition"]["target_rule_config_sha256"]
        or execution.get("runtime_config_sha256") != source["runtime_config_binding"]["target_sha256"]
        or len(selected) != 2 or len(completed) != 1 or reused or len(failed) != 1
        or completed | failed != selected or completed & failed
        or coverage.get("waived") != []
        or any(not isinstance(item, Mapping) or item.get("classification") != "budget"
               for item in coverage.get("failed", []))
        or not isinstance(comments, list)
        or any(not isinstance(item, Mapping) or item.get("path") not in completed_paths for item in comments)
        or not comments
        or capacity != expected_capacity
        or start != received
        or start.get("native_task", {}).get("id") != result.get("review_invocation_id")
        or activity.get("native_task_id") != result.get("review_invocation_id")
        or activity.get("status") != "COMPLETED" or activity.get("waiting_on") is not None
        or terminal.get("status") != "completed" or terminal.get("error_code") is not None
        or terminal.get("native_identity", {}).get("verdict") != "INCOMPLETE"
        or terminal.get("native_identity", {}).get("session_id") != child_session
        or lineage != expected_lineage
        or completed_paths & failed_paths
    ):
        raise ValueError("fresh result is not the exact consumed one-complete budget partial")
    session_copy = attempt / "native-session.jsonl"
    rows = [json.loads(line) for line in session_copy.read_text(encoding="utf-8").splitlines()]
    ends = [row for row in rows if isinstance(row, Mapping) and row.get("type") == "session_end"]
    if len(ends) != 1 or ends[0].get("run_manifest") != manifest:
        raise ValueError("fresh partial native Session terminal manifest is missing or changed")
    return {
        "root": root, "attempt": attempt, "outer": outer, "result": result, "raw": raw,
        "manifest": manifest, "execution": execution, "selected": coverage["selected"],
        "completed": completed, "failed": failed, "completed_paths": completed_paths,
        "remaining_paths": failed_paths, "evidence_sha256": hashes,
    }


def _validate_live_parent(
    fresh: Mapping[str, Any], partial: Mapping[str, Any], session_list: object,
    session_show: object,
) -> dict[str, Any]:
    child = partial["result"]["review"]["session_id"]
    if not isinstance(session_list, list) or not isinstance(session_show, Mapping) or set(
        session_show
    ) != {"summary", "items"}:
        raise ValueError("fresh partial Session inspection is invalid")
    matches = [row for row in session_list if isinstance(row, Mapping) and row.get("session_id") == child]
    summary, items = session_show["summary"], session_show["items"]
    source = partial["source"]
    facts = ("session_id", "diff_commit", "model", "review_mode", "aborted",
             "selected_files", "completed_files")
    if (
        len(matches) != 1 or not isinstance(summary, Mapping) or dict(matches[0]) != dict(summary)
        or not isinstance(items, list) or not items
        or summary.get("session_id") != child
        or summary.get("repo_dir", "").replace("\\", "/")
        != str(source["candidate_repository"]).replace("\\", "/")
        or summary.get("diff_commit") != source["candidate_commit"]
        or summary.get("model") != MODEL or summary.get("review_mode") != "commit"
        or summary.get("aborted") is not False or summary.get("selected_files") != 2
        or summary.get("completed_files") != 1 or summary.get("failed_files") != 1
        or summary.get("reused_files") != 0 or summary.get("waived_files") != 0
        or summary.get("llm_failures") != 1
        or summary.get("run_manifest") != partial["manifest"]
    ):
        raise ValueError("fresh partial Session is not the exact resumable child")
    session_path = Path(str(summary.get("file_path", ""))).resolve()
    if (
        not session_path.is_file()
        or _sha256(session_path) != _sha256(partial["attempt"] / "native-session.jsonl")
    ):
        raise ValueError("fresh partial Session store differs from preserved native evidence")
    return dict(summary)


def _session_evidence(
    fresh: Mapping[str, Any], partial: Mapping[str, Any], *, run_command: CommandRunner,
) -> tuple[object, object, dict[str, Any]]:
    source = partial["source"]
    endpoint = source.get("checker_endpoint")
    address = endpoint.get("address") if isinstance(endpoint, Mapping) else None
    runtime_root = Path(str(address.get("runtime_root", ""))).resolve() if isinstance(address, Mapping) else Path()
    wrapper = runtime_root / "ocr-slk.ps1"
    repository = str(Path(str(source["candidate_repository"])).resolve())
    child = str(partial["result"]["review"]["session_id"])
    session_list = _command_value(
        _ocr_command(wrapper, "session", "list", "--json", "--repo", repository), run_command
    )
    session_show = _command_value(
        _ocr_command(wrapper, "session", "show", "--json", "--repo", repository, child),
        run_command,
    )
    return session_list, session_show, _validate_live_parent(fresh, partial, session_list, session_show)


def _managed_identity(
    source: Mapping[str, Any], partial: Mapping[str, Any], summary: Mapping[str, Any],
    new_budget: int, *, run_command: CommandRunner,
) -> tuple[dict[str, Any], dict[str, Any]]:
    endpoint = source.get("checker_endpoint")
    address = endpoint.get("address") if isinstance(endpoint, Mapping) else None
    runtime_root = Path(str(address.get("runtime_root", ""))).resolve() if isinstance(address, Mapping) else Path()
    session_path = Path(str(summary["file_path"])).resolve()
    binding, transition, _preview = _validate_managed_target(
        runtime_root=runtime_root,
        repository=Path(str(source["candidate_repository"])).resolve(),
        state_root=session_path.parents[2],
        source_execution=partial["execution"], source_selected=partial["selected"],
        candidate_commit=str(source["candidate_commit"]), new_budget=new_budget,
        runner=run_command,
    )
    return binding, transition


def _derived_source(
    request: Mapping[str, Any], fresh: Mapping[str, Any], source: Mapping[str, Any],
    partial: Mapping[str, Any], session_summary: Mapping[str, Any],
) -> dict[str, Any]:
    value = copy.deepcopy(dict(source))
    session_path = Path(str(session_summary["file_path"])).resolve()
    value.update(
        recovery_invocation_id=request["recovery_invocation_id"],
        raw_review_path=str(partial["attempt"] / "ocrv-review.json"),
        session_record_path=str(session_path), session_record_sha256=_sha256(session_path),
        ocrv_session={key: session_summary[key] for key in (
            "session_id", "repo_dir", "diff_commit", "model", "review_mode", "start_time",
            "aborted", "selected_files", "completed_files",
        )},
        capacity_revision=request["capacity_revision"], ocrv_transition=request["ocrv_transition"],
        runtime_config_binding=request["runtime_config_binding"],
        owner_authorization=request["owner_authorization"],
        recovery_root=request["recovery_root"], result_path=request["result_path"],
    )
    immutable = dict(value["immutable_sha256"])
    immutable.update({
        "completed.json": _sha256(partial["attempt"] / "completed.json"),
        "ocrv-result.json": _sha256(partial["attempt"] / "ocrv-result.json"),
        "raw_review": _sha256(partial["attempt"] / "ocrv-review.json"),
    })
    value["immutable_sha256"] = immutable
    return value


def validate_fresh_partial_request(
    request: Mapping[str, Any], *, consumed: bool = False,
) -> dict[str, Any]:
    from . import worker_completion as wc

    if set(request) != _REQUEST_FIELDS or request.get("schema_version") != REQUEST_SCHEMA:
        raise wc.CompletionError(
            "CHECKER_TERMINAL_BUDGET_FRESH_PARTIAL_REQUEST_INVALID", "fresh-partial request is not closed"
        )
    fresh_path = Path(str(request["fresh_request_path"])).resolve()
    if (
        not fresh_path.is_file() or not _exact_digest(request.get("fresh_request_sha256"))
        or _sha256(fresh_path) != request["fresh_request_sha256"]
    ):
        raise wc.CompletionError(
            "CHECKER_TERMINAL_BUDGET_FRESH_PARTIAL_SOURCE_INVALID", "fresh-review request changed"
        )
    fresh = _read(fresh_path, "fresh-review request")
    fresh_validated = validate_fresh_review_request(fresh, consumed=True)
    source = fresh_validated["source_request"]
    partial_base = {"source": source}
    partial = {**partial_base, **_validate_partial_evidence(
        fresh, fresh_path, source, request.get("fresh_evidence_sha256")
    )}
    fresh_result = Path(str(fresh["result_path"])).resolve()
    if _sha256(fresh_result) != request.get("fresh_result_sha256"):
        raise wc.CompletionError(
            "CHECKER_TERMINAL_BUDGET_FRESH_PARTIAL_SOURCE_INVALID", "fresh-review result changed"
        )
    revision = request["capacity_revision"]
    old = revision.get("old") if isinstance(revision, Mapping) else None
    observed = revision.get("observed") if isinstance(revision, Mapping) else None
    new = revision.get("new") if isinstance(revision, Mapping) else None
    raw_summary = partial["raw"]["summary"]
    previous = source["capacity_revision"]["new"]
    if (
        not isinstance(revision, Mapping)
        or set(revision) != {"schema_version", "reason", "old", "observed", "new"}
        or revision.get("schema_version") != REVISION_SCHEMA
        or revision.get("reason") != "TERMINAL_TOKEN_BUDGET_EXHAUSTED"
        or old != previous
        or not isinstance(observed, Mapping)
        or observed != {name: raw_summary.get(name, 0) for name in (
            "total_tokens", "input_tokens", "output_tokens", "cache_read_tokens"
        )}
        or not isinstance(new, Mapping) or set(new) != set(previous)
        or new.get("max_tokens") != old.get("max_tokens")
        or new.get("timeout_minutes") != old.get("timeout_minutes")
        or type(new.get("max_tokens_budget")) is not int
        or new["max_tokens_budget"] <= observed["total_tokens"]
        or observed["total_tokens"] <= old["max_tokens_budget"]
    ):
        raise wc.CompletionError(
            "CHECKER_TERMINAL_BUDGET_FRESH_PARTIAL_CAPACITY_INVALID",
            "fresh-partial capacity revision is not exact or sufficient",
        )
    preflight_root = Path(str(request["recovery_root"])).resolve() / "preflight"
    session_paths = {name: preflight_root / name for name in ("session-list.json", "session-show.json")}
    supplied_session = request.get("parent_session_evidence_sha256")
    if (
        not isinstance(supplied_session, Mapping) or set(supplied_session) != set(session_paths)
        or any(not path.is_file() or _sha256(path) != supplied_session[name]
               for name, path in session_paths.items())
    ):
        raise wc.CompletionError(
            "CHECKER_TERMINAL_BUDGET_FRESH_PARTIAL_SESSION_INVALID", "parent Session evidence changed"
        )
    session_list = json.loads(session_paths["session-list.json"].read_text(encoding="utf-8"))
    session_show = _read(session_paths["session-show.json"], "parent Session detail")
    session_summary = _validate_live_parent(fresh, partial, session_list, session_show)
    authorization = request["owner_authorization"]
    if (
        request.get("strategy") != STRATEGY
        or request.get("parent_session_id") != partial["result"]["review"]["session_id"]
        or not isinstance(authorization, Mapping) or set(authorization) != _AUTHORIZATION_FIELDS
        or authorization.get("schema_version") != AUTHORIZATION_SCHEMA
        or authorization.get("authority") != "OWNER" or authorization.get("decision") != "APPROVED"
        or not _exact_identifier(authorization.get("authorization_id"))
        or not _exact_identifier(authorization.get("source_thread_id"))
        or not _authorized_at(authorization.get("occurred_at"))
        or authorization.get("fresh_request_sha256") != request["fresh_request_sha256"]
        or authorization.get("fresh_result_sha256") != request["fresh_result_sha256"]
        or authorization.get("capacity_revision_sha256") != canonical_json_sha256(revision)
        or authorization.get("ocrv_transition_sha256") != canonical_json_sha256(request["ocrv_transition"])
        or authorization.get("runtime_config_binding_sha256")
        != canonical_json_sha256(request["runtime_config_binding"])
    ):
        raise wc.CompletionError(
            "CHECKER_TERMINAL_BUDGET_FRESH_PARTIAL_AUTHORIZATION_INVALID",
            "Owner fresh-partial authorization is absent or changed",
        )
    expected_root = Path(str(fresh["recovery_root"])).resolve() / "resume-fresh-budget-partial" / str(
        request["recovery_invocation_id"]
    )
    if (
        Path(str(request["recovery_root"])).resolve() != expected_root
        or Path(str(request["result_path"])).resolve() != expected_root / "result.json"
    ):
        raise wc.CompletionError(
            "CHECKER_TERMINAL_BUDGET_FRESH_PARTIAL_REQUEST_INVALID", "fresh-partial output identity changed"
        )
    marker = _source_marker(fresh)
    if not consumed and marker.exists():
        raise wc.CompletionError(
            "CHECKER_TERMINAL_BUDGET_FRESH_PARTIAL_ALREADY_CONSUMED",
            "the exact fresh partial Session already consumed its one continuation",
        )
    if consumed and (not marker.is_file() or _read(marker, "fresh-partial source claim") != _claim_payload(request)):
        raise wc.CompletionError(
            "CHECKER_TERMINAL_BUDGET_FRESH_PARTIAL_SOURCE_INVALID", "fresh-partial source claim changed"
        )
    derived = _derived_source(request, fresh, source, partial, session_summary)
    validated = dict(fresh_validated["source_validated"])
    validated.update(
        target_ocrv_version=request["ocrv_transition"]["target_version"],
        target_rule_config_sha256=request["ocrv_transition"]["target_rule_config_sha256"],
        target_runtime_config_sha256=request["runtime_config_binding"]["target_sha256"],
    )
    return {
        "fresh_request": fresh, "source_request": derived, "source_validated": validated,
        "partial": partial, "session_summary": session_summary,
        "parent_completed_paths": partial["completed_paths"],
        "remaining_paths": partial["remaining_paths"],
    }


def verify_managed_target(
    request: Mapping[str, Any], validated: Mapping[str, Any],
    *, run_command: CommandRunner = _run_command,
) -> None:
    source = validated["source_request"]
    partial = validated["partial"]
    binding, transition = _managed_identity(
        source, partial, validated["session_summary"],
        int(request["capacity_revision"]["new"]["max_tokens_budget"]), run_command=run_command,
    )
    if binding != request["runtime_config_binding"] or transition != request["ocrv_transition"]:
        raise ValueError("managed fresh-partial target changed after preparation")


def prepare_fresh_partial_request(
    fresh_request_path: Path | str, *, max_tokens_budget: int, authorization_id: str,
    source_thread_id: str, occurred_at: str, output_path: Path | str,
    run_command: CommandRunner = _run_command,
) -> dict[str, Any]:
    from . import worker_completion as wc

    if (
        type(max_tokens_budget) is not int or max_tokens_budget <= 0
        or not _exact_identifier(authorization_id) or not _exact_identifier(source_thread_id)
        or not _authorized_at(occurred_at)
    ):
        raise ValueError("fresh-partial authorization or budget is incomplete")
    fresh_path = Path(fresh_request_path).resolve()
    fresh = _read(fresh_path, "fresh-review request")
    fresh_validated = validate_fresh_review_request(fresh, consumed=True)
    source = fresh_validated["source_request"]
    partial = {"source": source, **_validate_partial_evidence(fresh, fresh_path, source)}
    session_list, session_show, session_summary = _session_evidence(
        fresh, partial, run_command=run_command
    )
    binding, transition = _managed_identity(
        source, partial, session_summary, max_tokens_budget, run_command=run_command
    )
    old = dict(source["capacity_revision"]["new"])
    summary = partial["raw"]["summary"]
    revision = {
        "schema_version": REVISION_SCHEMA, "reason": "TERMINAL_TOKEN_BUDGET_EXHAUSTED",
        "old": old,
        "observed": {name: summary.get(name, 0) for name in (
            "total_tokens", "input_tokens", "output_tokens", "cache_read_tokens"
        )},
        "new": {**old, "max_tokens_budget": max_tokens_budget},
    }
    fresh_digest = _sha256(fresh_path)
    fresh_result_digest = _sha256(Path(str(fresh["result_path"])).resolve())
    authorization = {
        "schema_version": AUTHORIZATION_SCHEMA, "authority": "OWNER", "decision": "APPROVED",
        "authorization_id": authorization_id, "source_thread_id": source_thread_id,
        "fresh_request_sha256": fresh_digest, "fresh_result_sha256": fresh_result_digest,
        "capacity_revision_sha256": canonical_json_sha256(revision),
        "ocrv_transition_sha256": canonical_json_sha256(transition),
        "runtime_config_binding_sha256": canonical_json_sha256(binding),
        "occurred_at": occurred_at,
    }
    invocation = str(uuid.uuid5(
        _NAMESPACE,
        "|".join((fresh_digest, fresh_result_digest, canonical_json_sha256(authorization))),
    ))
    root = Path(str(fresh["recovery_root"])).resolve() / "resume-fresh-budget-partial" / invocation
    preflight = root / "preflight"
    _stable_json(preflight / "session-list.json", session_list)
    _stable_json(preflight / "session-show.json", session_show)
    request = {
        "schema_version": REQUEST_SCHEMA, "strategy": STRATEGY,
        "recovery_invocation_id": invocation, "fresh_request_path": str(fresh_path),
        "fresh_request_sha256": fresh_digest, "fresh_result_sha256": fresh_result_digest,
        "fresh_evidence_sha256": partial["evidence_sha256"],
        "parent_session_id": partial["result"]["review"]["session_id"],
        "parent_session_evidence_sha256": {
            name: _sha256(preflight / name) for name in ("session-list.json", "session-show.json")
        },
        "capacity_revision": revision, "ocrv_transition": transition,
        "runtime_config_binding": binding, "owner_authorization": authorization,
        "recovery_root": str(root), "result_path": str(root / "result.json"),
    }
    validate_fresh_partial_request(request)
    output = Path(output_path).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output = wc._write_or_reuse_stable_request(output, request)
    digest = _sha256(output)
    return {
        "schema_version": "slk.ocrv-terminal-budget-fresh-partial-preparation/v1",
        "status": "CHECKER_TERMINAL_BUDGET_FRESH_PARTIAL_REQUEST_READY",
        "run_id": source["run_id"], "cell_id": source["cell_id"],
        "candidate_commit": source["candidate_commit"],
        "parent_session_id": request["parent_session_id"],
        "request_path": str(output), "request_sha256": digest,
        "prepare_only_command": [
            *source["transport_command"], "resume-terminal-budget-fresh-partial",
            "--request", str(output), "--sha256", digest, "--prepare-only",
        ],
    }


def validate_fresh_partial_child(
    parent_raw: Mapping[str, Any], child_raw: Mapping[str, Any],
) -> None:
    parent_manifest = parent_raw.get("manifest")
    child_manifest = child_raw.get("manifest")
    if not isinstance(parent_manifest, Mapping) or not isinstance(child_manifest, Mapping):
        raise ValueError("fresh-partial parent or child manifest is absent")
    parent_coverage = parent_manifest.get("coverage")
    child_coverage = child_manifest.get("coverage")
    if not isinstance(parent_coverage, Mapping) or not isinstance(child_coverage, Mapping):
        raise ValueError("fresh-partial parent or child coverage is absent")
    selected = _identities(parent_coverage.get("selected"))
    parent_completed = _identities(parent_coverage.get("completed"))
    parent_failed = _identities(parent_coverage.get("failed"))
    child_selected = _identities(child_coverage.get("selected"))
    child_completed = _identities(child_coverage.get("completed"))
    child_reused = _identities(child_coverage.get("reused"))
    child_failed = _identities(child_coverage.get("failed"))
    parent_comments = parent_raw.get("comments")
    child_comments = child_raw.get("comments")
    parent_findings = _without_provider_thinking(parent_comments)
    child_findings = _without_provider_thinking(child_comments)
    if (
        selected != child_selected or child_reused != parent_completed
        or child_completed & parent_completed or not parent_failed <= child_completed | child_failed
        or child_completed | child_reused | child_failed != selected
        or child_coverage.get("waived") != []
        or not isinstance(parent_comments, list) or not isinstance(child_comments, list)
        or any(comment not in child_findings for comment in parent_findings)
        or any(not isinstance(comment, Mapping) or comment.get("path") not in
               {identity[1] for identity in child_completed | child_reused}
               for comment in child_findings)
    ):
        raise ValueError("fresh-partial resume re-reviewed, lost, or changed preserved evidence")
