"""Thin fresh-review adapter for one consumed OCRV rule-identity rejection."""

from __future__ import annotations

import json
import re
import uuid
from collections.abc import Callable, Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

from .contracts import canonical_json_sha256
from .native_activity import process_probe as default_process_probe
from .terminal_budget import (
    _read,
    _run_command,
    _sha256,
    _validate_managed_target,
    validate as validate_terminal_budget,
)


REQUEST_SCHEMA = "slk.ocrv-terminal-budget-fresh-review-request/v1"
RESULT_SCHEMA = "slk.ocrv-terminal-budget-fresh-review-result/v1"
AUTHORIZATION_SCHEMA = "slk.owner-terminal-budget-fresh-review-authorization/v1"
SOURCE_CONSUMPTION_SCHEMA = "slk.ocrv-terminal-budget-fresh-review-source-consumption/v1"
STRATEGY = "FRESH_FULL_REVIEW_NO_CHECKPOINT_REUSE"
PROVIDER = "dashscope-tokenplan"
MODEL = "qwen3.8-max"
_NAMESPACE = uuid.UUID("f4826331-6657-5d4b-a853-f236b0d8ff97")
_REJECTION_FILES = {
    "native-start.received.json", "native-activity.json", "ocrv-capacity-request.json",
    "ocrv-result.json", "ocrv.stderr.txt", "ocrv.stdout.txt",
}
_REQUEST_FIELDS = {
    "schema_version", "strategy", "recovery_invocation_id", "source_request_path",
    "source_request_sha256", "rejection_native_attempt_path", "rejection_evidence_sha256",
    "source_rejection_sha256", "owner_authorization", "recovery_root", "result_path",
}
_AUTHORIZATION_FIELDS = {
    "schema_version", "authority", "decision", "authorization_id", "source_thread_id",
    "source_request_sha256", "source_rejection_sha256", "occurred_at",
}

CommandRunner = Callable[[list[str]], Any]
ProcessProbe = Callable[[int, str], Mapping[str, Any]]


def _exact_digest(value: object) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _exact_identifier(value: object) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}", value) is not None


def _authorized_at(value: object) -> bool:
    if not isinstance(value, str) or value != value.strip():
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None


def _rejection_paths(source: Mapping[str, Any]) -> dict[str, Path]:
    root = Path(str(source["recovery_root"])).resolve() / "native-attempt"
    return {name: root / name for name in _REJECTION_FILES}


def _expected_diagnostic(parent_session_id: str) -> str:
    return (
        "Error: resume rejected: review rule identity changed — either a rule text layer "
        "(custom, project, global or system) or the include/exclude file filter differs from "
        f'session "{parent_session_id}"; start a new review instead of resuming'
    )


def _validate_rejection(
    source: Mapping[str, Any], *, process_probe: ProcessProbe = default_process_probe,
) -> dict[str, Any]:
    paths = _rejection_paths(source)
    if any(not path.is_file() for path in paths.values()):
        raise ValueError("terminal-budget rule rejection evidence is incomplete")
    root = next(iter(paths.values())).parent
    forbidden = {
        "ocrv-review.json", "native-session.jsonl", "resume-lineage.json", "started.json",
        "completed.json", "committed-terminal.json",
    }
    if (
        {path.name for path in root.iterdir()} != _REJECTION_FILES
        or any((root / name).exists() for name in forbidden)
        or Path(str(source["result_path"])).exists()
    ):
        raise ValueError("terminal-budget rejection already produced review or terminal evidence")

    start = _read(paths["native-start.received.json"], "native start")
    activity = _read(paths["native-activity.json"], "native activity")
    capacity = _read(paths["ocrv-capacity-request.json"], "capacity request")
    result = _read(paths["ocrv-result.json"], "OCRV result")
    stderr = paths["ocrv.stderr.txt"].read_text(encoding="utf-8")
    source_original = _read(
        Path(str(source["native_attempt_path"])).resolve() / "ocrv-request.json",
        "original OCRV request",
    )
    expected_capacity = dict(source_original)
    expected_capacity["capacity"] = {
        **dict(source_original.get("capacity", {})), **source["capacity_revision"]["new"]
    }
    parent = str(source["ocrv_session"]["session_id"])
    diagnostic = _expected_diagnostic(parent)
    lines = [line for line in stderr.splitlines() if line]
    warning = re.compile(
        r"^\[ocr\] --background-file content is [1-9][0-9]* characters, "
        r"exceeding the recommended 2000 \(continuing but review quality might be impacted\)$"
    )
    process = start.get("process") if isinstance(start, Mapping) else None
    native_task = start.get("native_task") if isinstance(start, Mapping) else None
    review = result.get("review") if isinstance(result, Mapping) else None
    last_event = activity.get("last_event") if isinstance(activity, Mapping) else None
    invocation = result.get("review_invocation_id") if isinstance(result, Mapping) else None
    if (
        paths["ocrv.stdout.txt"].read_bytes() != b""
        or lines.count(diagnostic) != 1
        or len(lines) not in {1, 2}
        or any(line != diagnostic and warning.fullmatch(line) is None for line in lines)
        or capacity != expected_capacity
        or not isinstance(process, Mapping)
        or isinstance(process.get("pid"), bool) or not isinstance(process.get("pid"), int)
        or process["pid"] <= 0
        or not isinstance(process.get("creation_time"), str)
        or not process["creation_time"]
        or not isinstance(native_task, Mapping) or native_task.get("kind") != "ocrv-review"
        or native_task.get("id") != invocation
        or start.get("schema_version") != "slk.native-start/v2"
        or start.get("status") != "STARTED" or start.get("adapter") != "ocrv-checker"
        or start.get("run_id") != source["run_id"] or start.get("cell_id") != source["cell_id"]
        or start.get("message_id") != source["candidate_message_id"]
        or start.get("request_sha256") != source["payload_sha256"]
        or start.get("native_request_sha256") != _sha256(paths["ocrv-capacity-request.json"])
        or result.get("schema_version") != "slk.ocrv-d1-result/v1"
        or result.get("run_id") != source["run_id"] or result.get("cell_id") != source["cell_id"]
        or result.get("verdict") != "INCOMPLETE"
        or result.get("reason_codes") != ["OCR_EXIT_1", "OCR_RESULT_MISSING_OR_INVALID"]
        or result.get("findings") != [] or not isinstance(review, Mapping)
        or set(review) != {"status", "provider", "model", "session_id", "exit_code"}
        or any(review.get(name) is not None for name in ("status", "provider", "model", "session_id"))
        or review.get("exit_code") != 1
        or result.get("request_sha256") != _sha256(paths["ocrv-capacity-request.json"])
        or activity.get("schema_version") != "slk.native-task-activity/v1"
        or activity.get("adapter") != "ocrv-checker" or activity.get("run_id") != source["run_id"]
        or activity.get("cell_id") != source["cell_id"]
        or activity.get("message_id") != source["candidate_message_id"]
        or activity.get("native_task_id") != invocation or activity.get("status") != "FAILED"
        or activity.get("waiting_on") is not None or not isinstance(last_event, Mapping)
        or last_event.get("kind") != "OCRV_PROCESS_EXITED" or last_event.get("exit_code") != 1
    ):
        raise ValueError("native failure is not the exact pre-LLM rule-identity rejection")
    observed = process_probe(process["pid"], str(process["creation_time"]))
    if observed.get("exists") is True and observed.get("identity_matches") is True:
        raise ValueError("rejected OCRV process is still active")
    evidence = {name: _sha256(path) for name, path in paths.items()}
    return {
        "native_attempt_path": str(root),
        "evidence_sha256": evidence,
        "source_rejection_sha256": canonical_json_sha256(evidence),
    }


def verify_managed_target(
    source: Mapping[str, Any], *, run_command: CommandRunner = _run_command,
) -> None:
    endpoint = source.get("checker_endpoint")
    address = endpoint.get("address") if isinstance(endpoint, Mapping) else None
    runtime_root = Path(str(address.get("runtime_root", ""))).resolve() if isinstance(address, Mapping) else Path()
    session_path = Path(str(source.get("session_record_path", ""))).resolve()
    raw = _read(Path(str(source["raw_review_path"])).resolve(), "parent OCRV review")
    manifest = raw.get("manifest") if isinstance(raw, Mapping) else None
    execution = manifest.get("execution") if isinstance(manifest, Mapping) else None
    coverage = manifest.get("coverage") if isinstance(manifest, Mapping) else None
    selected = coverage.get("selected") if isinstance(coverage, Mapping) else None
    if not runtime_root.is_dir() or len(session_path.parents) < 3 or not isinstance(
        execution, Mapping
    ) or not isinstance(selected, list):
        raise ValueError("managed fresh-review target identity is unavailable")
    binding, transition, _preview = _validate_managed_target(
        runtime_root=runtime_root,
        repository=Path(str(source["candidate_repository"])).resolve(),
        state_root=session_path.parents[2],
        source_execution=execution,
        source_selected=selected,
        candidate_commit=str(source["candidate_commit"]),
        new_budget=int(source["capacity_revision"]["new"]["max_tokens_budget"]),
        runner=run_command,
    )
    if binding != source["runtime_config_binding"] or transition != source["ocrv_transition"]:
        raise ValueError("managed fresh-review target changed after preparation")


def _claim_payload(request: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": SOURCE_CONSUMPTION_SCHEMA,
        "source_request_sha256": request["source_request_sha256"],
        "source_rejection_sha256": request["source_rejection_sha256"],
        "authorization_sha256": canonical_json_sha256(request["owner_authorization"]),
        "recovery_invocation_id": request["recovery_invocation_id"],
    }


def claim_fresh_review_source(request: Mapping[str, Any]) -> Path:
    from . import worker_completion as wc

    marker = Path(str(request["recovery_root"])).resolve().parent / "source-consumed.json"
    marker.parent.mkdir(parents=True, exist_ok=True)
    try:
        with marker.open("x", encoding="utf-8") as stream:
            json.dump(_claim_payload(request), stream, sort_keys=True)
            stream.write("\n")
    except FileExistsError as exc:
        raise wc.CompletionError(
            "CHECKER_TERMINAL_BUDGET_FRESH_ALREADY_CONSUMED",
            "the exact rule-identity rejection already consumed its one fresh review",
        ) from exc
    return marker


def validate_fresh_review_request(
    request: Mapping[str, Any], *, consumed: bool = False,
    process_probe: ProcessProbe = default_process_probe,
) -> dict[str, Any]:
    from . import worker_completion as wc

    if set(request) != _REQUEST_FIELDS or request.get("schema_version") != REQUEST_SCHEMA:
        raise wc.CompletionError(
            "CHECKER_TERMINAL_BUDGET_FRESH_REQUEST_INVALID", "fresh-review request is not closed"
        )
    source_raw = Path(str(request["source_request_path"]))
    source_path = source_raw.resolve()
    try:
        invocation_valid = str(uuid.UUID(str(request["recovery_invocation_id"]))) == request[
            "recovery_invocation_id"
        ]
    except (ValueError, TypeError, AttributeError):
        invocation_valid = False
    if (
        not source_raw.is_absolute()
        or not source_path.is_file()
        or not invocation_valid
        or not _exact_digest(request["source_request_sha256"])
        or _sha256(source_path) != request["source_request_sha256"]
    ):
        raise wc.CompletionError(
            "CHECKER_TERMINAL_BUDGET_FRESH_SOURCE_INVALID", "terminal-budget source request changed"
        )
    source = _read(source_path, "terminal-budget source request")
    source_validated = validate_terminal_budget(source, consumed=True)
    rejection = _validate_rejection(source, process_probe=process_probe)
    authorization = request["owner_authorization"]
    if (
        request.get("strategy") != STRATEGY
        or request.get("rejection_native_attempt_path") != rejection["native_attempt_path"]
        or request.get("rejection_evidence_sha256") != rejection["evidence_sha256"]
        or request.get("source_rejection_sha256") != rejection["source_rejection_sha256"]
        or source["ocrv_transition"]["source_rule_config_sha256"]
        == source["ocrv_transition"]["target_rule_config_sha256"]
    ):
        raise wc.CompletionError(
            "CHECKER_TERMINAL_BUDGET_FRESH_IDENTITY_INVALID",
            "fresh review does not bind the exact source rejection",
        )
    if (
        not isinstance(authorization, Mapping)
        or set(authorization) != _AUTHORIZATION_FIELDS
        or authorization.get("schema_version") != AUTHORIZATION_SCHEMA
        or authorization.get("authority") != "OWNER" or authorization.get("decision") != "APPROVED"
        or not _exact_identifier(authorization.get("authorization_id"))
        or not _exact_identifier(authorization.get("source_thread_id"))
        or not _authorized_at(authorization.get("occurred_at"))
        or authorization.get("source_request_sha256") != request["source_request_sha256"]
        or authorization.get("source_rejection_sha256") != request["source_rejection_sha256"]
    ):
        raise wc.CompletionError(
            "CHECKER_TERMINAL_BUDGET_FRESH_AUTHORIZATION_INVALID",
            "Owner fresh-review compatibility authorization is absent or changed",
        )
    recovery = Path(str(request["recovery_root"])).resolve()
    expected = Path(str(source["recovery_root"])).resolve() / "fresh-review-compatibility" / str(
        request["recovery_invocation_id"]
    )
    marker = expected.parent / "source-consumed.json"
    if recovery != expected or Path(str(request["result_path"])).resolve() != expected / "result.json":
        raise wc.CompletionError(
            "CHECKER_TERMINAL_BUDGET_FRESH_REQUEST_INVALID", "fresh-review output identity changed"
        )
    if not consumed and marker.exists():
        raise wc.CompletionError(
            "CHECKER_TERMINAL_BUDGET_FRESH_ALREADY_CONSUMED",
            "the exact rule-identity rejection already consumed its one fresh review",
        )
    if consumed and (
        not marker.is_file()
        or _read(marker, "fresh-review source consumption") != _claim_payload(request)
    ):
        raise wc.CompletionError(
            "CHECKER_TERMINAL_BUDGET_FRESH_SOURCE_INVALID", "fresh-review source claim is missing or changed"
        )
    correction = dict(source_validated["d1_correction"])
    correction["correction_id"] = request["recovery_invocation_id"]
    return {
        "source_request": source,
        "source_validated": source_validated,
        "rejection": rejection,
        "recovery_root": recovery,
        "role_host_binding": source_validated["role_host_binding"],
        "d1_correction": correction,
        "target_ocrv_version": source_validated["target_ocrv_version"],
        "target_rule_config_sha256": source_validated["target_rule_config_sha256"],
        "target_runtime_config_sha256": source_validated["target_runtime_config_sha256"],
    }


def prepare_fresh_review_request(
    source_request_path: Path | str, *, authorization_id: str, source_thread_id: str,
    occurred_at: str, output_path: Path | str, run_command: CommandRunner = _run_command,
    process_probe: ProcessProbe = default_process_probe,
) -> dict[str, Any]:
    from . import worker_completion as wc

    if (
        not _exact_identifier(authorization_id)
        or not _exact_identifier(source_thread_id)
        or not _authorized_at(occurred_at)
    ):
        raise ValueError("fresh-review compatibility authorization is incomplete")
    source_path = Path(source_request_path).resolve()
    source = _read(source_path, "terminal-budget source request")
    validate_terminal_budget(source, consumed=True)
    rejection = _validate_rejection(source, process_probe=process_probe)
    verify_managed_target(source, run_command=run_command)
    source_digest = _sha256(source_path)
    authorization = {
        "schema_version": AUTHORIZATION_SCHEMA, "authority": "OWNER", "decision": "APPROVED",
        "authorization_id": authorization_id, "source_thread_id": source_thread_id,
        "source_request_sha256": source_digest,
        "source_rejection_sha256": rejection["source_rejection_sha256"], "occurred_at": occurred_at,
    }
    invocation = str(uuid.uuid5(
        _NAMESPACE,
        "|".join((source_digest, rejection["source_rejection_sha256"], canonical_json_sha256(authorization))),
    ))
    root = Path(str(source["recovery_root"])).resolve() / "fresh-review-compatibility" / invocation
    request = {
        "schema_version": REQUEST_SCHEMA, "strategy": STRATEGY,
        "recovery_invocation_id": invocation, "source_request_path": str(source_path),
        "source_request_sha256": source_digest,
        "rejection_native_attempt_path": rejection["native_attempt_path"],
        "rejection_evidence_sha256": rejection["evidence_sha256"],
        "source_rejection_sha256": rejection["source_rejection_sha256"],
        "owner_authorization": authorization, "recovery_root": str(root),
        "result_path": str(root / "result.json"),
    }
    validate_fresh_review_request(request, process_probe=process_probe)
    output_path = Path(output_path).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output = wc._write_or_reuse_stable_request(output_path, request)
    digest = _sha256(output)
    return {
        "schema_version": "slk.ocrv-terminal-budget-fresh-review-preparation/v1",
        "status": "CHECKER_TERMINAL_BUDGET_FRESH_REQUEST_READY",
        "run_id": source["run_id"], "cell_id": source["cell_id"],
        "candidate_commit": source["candidate_commit"],
        "parent_session_id": source["ocrv_session"]["session_id"],
        "source_rejection_sha256": rejection["source_rejection_sha256"],
        "request_path": str(output), "request_sha256": digest,
        "prepare_only_command": [
            *source["transport_command"], "resume-terminal-budget-fresh-review",
            "--request", str(output), "--sha256", digest, "--prepare-only",
        ],
    }


def validate_fresh_child(
    parent_raw: Mapping[str, Any], child_raw: Mapping[str, Any], *, child_records: list[dict[str, Any]],
    target_ocrv_version: str, target_rule_config_sha256: str,
    target_runtime_config_sha256: str,
) -> None:
    parent_manifest, child_manifest = parent_raw.get("manifest"), child_raw.get("manifest")
    if not isinstance(parent_manifest, Mapping) or not isinstance(child_manifest, Mapping):
        raise ValueError("fresh review manifests are missing")
    parent_coverage, child_coverage = parent_manifest.get("coverage"), child_manifest.get("coverage")
    execution = child_manifest.get("execution")
    starts = [row for row in child_records if row.get("type") == "session_start"]
    ends = [row for row in child_records if row.get("type") == "session_end"]
    if (
        parent_manifest.get("input") != child_manifest.get("input")
        or not isinstance(parent_coverage, Mapping) or not isinstance(child_coverage, Mapping)
        or child_coverage.get("selected") != parent_coverage.get("selected")
        or child_coverage.get("reused") != [] or not isinstance(execution, Mapping)
        or execution.get("ocr_version") != target_ocrv_version
        or execution.get("provider") != PROVIDER or execution.get("model") != MODEL
        or execution.get("rule_config_sha256") != target_rule_config_sha256
        or execution.get("runtime_config_sha256") != target_runtime_config_sha256
        or len(starts) != 1 or len(ends) != 1
        or any(row.get("type") == "resume_lineage" for row in child_records)
        or ends[0].get("run_manifest") != child_manifest
    ):
        raise ValueError("fresh review changed the candidate, rules, model, or full coverage")
