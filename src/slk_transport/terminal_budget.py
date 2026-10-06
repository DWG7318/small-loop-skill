"""Closed admission for one ordinary OCRV terminal-budget D1 continuation."""

from __future__ import annotations

import hashlib
import json
import re
import struct
import subprocess
import uuid
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

from .contracts import canonical_json_sha256


REQUEST_SCHEMA = "slk.ocrv-terminal-budget-resume-request/v1"
RESULT_SCHEMA = "slk.ocrv-terminal-budget-resume-result/v1"
REVISION_SCHEMA = "slk.ocrv-terminal-budget-capacity-revision/v1"
AUTHORIZATION_SCHEMA = "slk.owner-capacity-revision-authorization/v1"
OCRV_TRANSITION_SCHEMA = "slk.ocrv-version-transition/v1"
RUNTIME_CONFIG_BINDING_SCHEMA = "slk.ocrv-runtime-config-binding/v1"

BASE_FIELDS = {
    "method_version", "recovery_invocation_id", "run_id", "go_id", "cell_id",
    "attempt", "plan_revision", "runtime_revision", "token_sequence",
    "worker_role_instance_id", "checker_role_instance_id", "checker_endpoint_version",
    "checker_endpoint", "runtime_projection_path", "runtime_projection_sha256",
    "candidate_repository", "candidate_commit", "candidate_parent",
    "candidate_message_id", "payload_sha256", "candidate_submitted_event_id",
    "transport_started_event_id", "commit_request_path", "commit_request_sha256",
    "native_attempt_path", "raw_review_path", "immutable_sha256",
    "checker_credential_path", "state_command", "transport_command", "result_path",
}
EXTRA_FIELDS = {
    "d1_started_event_id", "d1_incomplete_event_id", "ocrv_preflight_path",
    "ocrv_preflight_sha256", "background_path", "background_sha256",
    "native_activity_path", "native_activity_sha256", "session_record_path",
    "session_record_sha256", "ocrv_session", "capacity_revision",
    "ocrv_transition", "runtime_config_binding", "owner_authorization",
    "role_host_binding_path", "role_host_binding_sha256", "recovery_root",
}
CAPACITY_FIELDS = {"max_tokens", "max_tokens_budget", "timeout_minutes"}
USAGE_FIELDS = {"total_tokens", "input_tokens", "output_tokens", "cache_read_tokens"}
RUNTIME_CONFIG_FIELDS = {
    "schema_version", "protocol", "model", "endpoint_host", "language", "timeout",
    "concurrency", "source_sha256", "target_sha256",
}
PREPARATION_SCHEMA = "slk.ocrv-terminal-budget-resume-preparation/v1"
_PREPARATION_NAMESPACE = uuid.UUID("2b8fd4cf-a1bb-5dd4-8b7b-c043f9633388")
_MAX_DISCOVERY_FILES = 10_000
_MAX_DISCOVERY_JSON_BYTES = 32 * 1024 * 1024


CommandRunner = Callable[[list[str]], subprocess.CompletedProcess[str]]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _run_command(command: list[str]) -> subprocess.CompletedProcess[str]:
    from .process import windows_no_window_kwargs

    return subprocess.run(
        command,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        **windows_no_window_kwargs(),
    )


def _command_json(command: list[str], runner: CommandRunner) -> dict[str, Any]:
    completed = runner(command)
    if completed.returncode != 0:
        raise ValueError("OCRV read-only inspection failed")
    try:
        value = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise ValueError("OCRV read-only inspection returned invalid JSON") from exc
    if not isinstance(value, dict):
        raise ValueError("OCRV read-only inspection did not return an object")
    return value


def _ocr_command(wrapper: Path, *arguments: str) -> list[str]:
    if wrapper.suffix.lower() == ".ps1":
        return [
            "powershell.exe", "-NoLogo", "-NoProfile", "-ExecutionPolicy", "Bypass",
            "-File", str(wrapper), *arguments,
        ]
    return [str(wrapper), *arguments]


def _json_candidates(root: Path) -> list[tuple[Path, dict[str, Any]]]:
    candidates: list[tuple[Path, dict[str, Any]]] = []
    count = 0
    for path in sorted(root.rglob("*.json"), key=lambda item: str(item).lower()):
        count += 1
        if count > _MAX_DISCOVERY_FILES:
            raise ValueError("Run evidence discovery exceeded its bounded file count")
        try:
            if not path.is_file() or path.stat().st_size > _MAX_DISCOVERY_JSON_BYTES:
                continue
            value = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
        if isinstance(value, dict):
            candidates.append((path.resolve(), value))
    return candidates


def _event_details(event: Mapping[str, Any]) -> Mapping[str, Any] | None:
    try:
        value = json.loads(str(event.get("details_json", "")))
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, Mapping) else None


def _one(items: list[Any], label: str) -> Any:
    if len(items) != 1:
        raise ValueError(f"{label} is missing or ambiguous")
    return items[0]


def _discover_source_projection(
    candidates: list[tuple[Path, dict[str, Any]]], *, run_id: str,
    message_id: str, terminal_sha256: str, result_sha256: str,
) -> tuple[Path, dict[str, Any], Mapping[str, Any], Mapping[str, Any]]:
    matches: list[tuple[Path, dict[str, Any], Mapping[str, Any], Mapping[str, Any]]] = []
    for path, value in candidates:
        if value.get("schema_version") != "slk.bi.run/v1" or value.get("run_id") != run_id:
            continue
        events = value.get("events")
        if not isinstance(events, list):
            continue
        starts: list[Mapping[str, Any]] = []
        incompletes: list[Mapping[str, Any]] = []
        for event in events:
            if not isinstance(event, Mapping):
                continue
            details = _event_details(event)
            if details is None or details.get("candidate_message_id") != message_id:
                continue
            if event.get("event_type") == "D1_STARTED":
                starts.append(event)
            if (
                event.get("event_type") == "D1_INCOMPLETE"
                and details.get("native_terminal_sha256") == terminal_sha256
                and details.get("native_result_sha256") == result_sha256
                and details.get("verdict") == "INCOMPLETE"
            ):
                incompletes.append(event)
        if len(starts) == 1 and len(incompletes) == 1:
            administrative = value.get("administrative_snapshot")
            if (
                isinstance(administrative, Mapping)
                and administrative.get("latest_event_id") == incompletes[0].get("event_id")
            ):
                matches.append((path, value, starts[0], incompletes[0]))
    if not matches:
        raise ValueError("frozen D1 INCOMPLETE projection is missing")
    canonical = {canonical_json_sha256(item[1]) for item in matches}
    if len(canonical) != 1:
        raise ValueError("frozen D1 INCOMPLETE projection is ambiguous")
    return matches[0]


def _discover_commit_request(
    candidates: list[tuple[Path, dict[str, Any]]], *, run_id: str,
    message_id: str, event_id: str,
) -> tuple[Path, dict[str, Any]]:
    matches = [
        (path, value)
        for path, value in candidates
        if value.get("run_id") == run_id
        and value.get("message_id") == message_id
        and value.get("event_id") == event_id
        and value.get("payload_type") == "CANDIDATE_READY"
        and isinstance(value.get("start_evidence"), Mapping)
    ]
    return _one(matches, "commit-delivery-start request")


def _validate_managed_target(
    *, runtime_root: Path, repository: Path, state_root: Path,
    source_execution: Mapping[str, Any], source_selected: list[Any],
    candidate_commit: str, new_budget: int, runner: CommandRunner,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    capability = _read(runtime_root / "slk-checker-capabilities.json", "OCRV capabilities")
    identity = capability.get("terminal_budget_resume_identity")
    if not isinstance(identity, Mapping) or set(identity) != {
        "ocrv_version", "provider", "model", "protocol", "endpoint_host",
        "language", "timeout", "concurrency", "rule_config_sha256", "managed_rule_files",
    }:
        raise ValueError("managed OCRV terminal-budget identity is unavailable")
    rule_files = identity.get("managed_rule_files")
    if not isinstance(rule_files, Mapping) or not rule_files:
        raise ValueError("managed OCRV rule identity is unavailable")
    for relative, digest in rule_files.items():
        path = (runtime_root / str(relative)).resolve()
        if (
            not isinstance(relative, str)
            or not isinstance(digest, str)
            or path.parent != runtime_root.resolve() / Path(relative).parent
            or not path.is_file()
            or _sha256(path) != digest
        ):
            raise ValueError("managed OCRV rule file changed")
    if (repository / ".opencodereview" / "rule.json").exists() or (
        state_root / "rule.json"
    ).exists():
        raise ValueError("project or global OCRV rule would change the managed review identity")

    wrapper = runtime_root / "ocr-slk.ps1"
    version = runner(_ocr_command(wrapper, "--version"))
    if version.returncode != 0 or re.search(r"v\d+\.\d+\.\d+", version.stdout or "") is None:
        raise ValueError("OCRV version cannot be verified")
    actual_version = re.search(r"v\d+\.\d+\.\d+", version.stdout).group(0)
    if actual_version != identity.get("ocrv_version"):
        raise ValueError("installed OCRV version differs from the managed resume identity")

    config = _read(state_root / "config.json", "OCRV config")
    provider_name = config.get("provider")
    providers = config.get("providers")
    provider = providers.get(provider_name) if isinstance(providers, Mapping) else None
    if (
        provider_name != identity.get("provider")
        or not isinstance(provider, Mapping)
        or provider.get("model") != identity.get("model")
        or config.get("language") != identity.get("language")
    ):
        raise ValueError("OCRV provider, model, or language changed")

    preview = _command_json(
        _ocr_command(
            wrapper, "review", "--repo", str(repository), "--commit",
            candidate_commit, "--preview", "--format", "json",
        ),
        runner,
    )
    files = preview.get("files")
    selected_paths = {
        str(item.get("path"))
        for item in source_selected
        if isinstance(item, Mapping) and item.get("path")
    }
    preview_paths = {
        str(item.get("path"))
        for item in files
        if isinstance(item, Mapping) and item.get("will_review") is True
    } if isinstance(files, list) else set()
    if (
        not selected_paths
        or preview_paths != selected_paths
        or preview.get("reviewable_count") != len(selected_paths)
        or preview.get("excluded_count") != 0
    ):
        raise ValueError("OCRV target preview changed the frozen candidate coverage")

    binding = {
        "schema_version": RUNTIME_CONFIG_BINDING_SCHEMA,
        "protocol": identity["protocol"],
        "model": identity["model"],
        "endpoint_host": identity["endpoint_host"],
        "language": identity["language"],
        "timeout": identity["timeout"],
        "concurrency": identity["concurrency"],
        "source_sha256": source_execution.get("runtime_config_sha256"),
        "target_sha256": "",
    }
    binding["target_sha256"] = ocrv_runtime_config_sha256(binding, new_budget)
    transition = {
        "schema_version": OCRV_TRANSITION_SCHEMA,
        "reason": "OWNER_REQUESTED_TOOL_UNIFICATION",
        "source_version": source_execution.get("ocr_version"),
        "target_version": identity["ocrv_version"],
        "source_rule_config_sha256": source_execution.get("rule_config_sha256"),
        "target_rule_config_sha256": identity["rule_config_sha256"],
    }
    return binding, transition, preview


def prepare_terminal_budget_request(
    native_attempt_path: Path | str,
    role_host_binding_path: Path | str,
    *,
    max_tokens_budget: int,
    authorization_id: str,
    source_thread_id: str,
    occurred_at: str,
    output_path: Path | str,
    run_command: CommandRunner = _run_command,
    load_current_projection: Callable[[str, list[str]], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Prepare and validate one exact resume request without invoking an LLM."""

    from . import worker_completion as wc

    if (
        isinstance(max_tokens_budget, bool)
        or not isinstance(max_tokens_budget, int)
        or max_tokens_budget <= 0
        or not all(
            isinstance(value, str) and value and value == value.strip()
            for value in (authorization_id, source_thread_id, occurred_at)
        )
    ):
        raise ValueError("terminal-budget preparation authorization is incomplete")
    try:
        datetime.fromisoformat(occurred_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("terminal-budget authorization time is invalid") from exc

    attempt = Path(native_attempt_path).resolve()
    role_host_path = Path(role_host_binding_path).resolve()
    destination = Path(output_path).resolve()
    if not attempt.is_dir() or not role_host_path.is_file() or not destination.is_absolute():
        raise ValueError("terminal-budget source paths are unavailable")
    endpoint = _read(attempt / "endpoint.json", "original Checker endpoint")
    envelope = _read(attempt / "envelope.json", "original Checker envelope")
    started = _read(attempt / "started.json", "original Checker start")
    original_request = _read(attempt / "ocrv-request.json", "original OCRV request")
    terminal = _read(attempt / "completed.json", "original Checker terminal")
    result = _read(attempt / "ocrv-result.json", "original OCRV result")
    role_host = _read(role_host_path, "frozen RoleHost binding")
    identity = terminal.get("native_identity")
    artifacts = result.get("artifacts")
    if not isinstance(identity, Mapping) or not isinstance(artifacts, Mapping):
        raise ValueError("original Checker terminal identity is unavailable")
    raw_path = Path(str(artifacts.get("raw_review", ""))).resolve()
    background_path = Path(str(artifacts.get("background", ""))).resolve()
    raw = _read(raw_path, "original OCRV raw review")
    manifest = raw.get("manifest")
    execution = manifest.get("execution") if isinstance(manifest, Mapping) else None
    coverage = manifest.get("coverage") if isinstance(manifest, Mapping) else None
    selected = coverage.get("selected") if isinstance(coverage, Mapping) else None
    summary = raw.get("summary")
    manifest_input = manifest.get("input") if isinstance(manifest, Mapping) else None
    if (
        not isinstance(execution, Mapping)
        or not isinstance(selected, list)
        or not isinstance(summary, Mapping)
        or not isinstance(manifest_input, Mapping)
    ):
        raise ValueError("original OCRV manifest is unavailable")

    run_id = str(envelope.get("run_id", ""))
    message_id = str(envelope.get("message_id", ""))
    run_root = role_host_path.parent.parent.resolve()
    candidates = _json_candidates(run_root)
    projection_path, projection, d1_started, d1_incomplete = _discover_source_projection(
        candidates,
        run_id=run_id,
        message_id=message_id,
        terminal_sha256=_sha256(attempt / "completed.json"),
        result_sha256=_sha256(attempt / "ocrv-result.json"),
    )
    events = projection.get("events")
    candidate_matches: list[Mapping[str, Any]] = []
    transport_matches: list[Mapping[str, Any]] = []
    if isinstance(events, list):
        for event in events:
            if not isinstance(event, Mapping):
                continue
            details = _event_details(event)
            if details is None:
                continue
            if event.get("event_type") == "CANDIDATE_SUBMITTED" and details.get(
                "handoff_message_id"
            ) == message_id:
                candidate_matches.append(event)
            if event.get("event_type") == "TRANSPORT_STARTED" and details.get(
                "message_id"
            ) == message_id:
                transport_matches.append(event)
    candidate_event = _one(candidate_matches, "candidate event")
    transport_event = _one(transport_matches, "transport event")
    commit_path, _commit = _discover_commit_request(
        candidates,
        run_id=run_id,
        message_id=message_id,
        event_id=str(transport_event["event_id"]),
    )

    runtime_snapshot = projection.get("runtime_snapshot")
    roles = role_host.get("roles")
    checker_binding = roles.get("checker") if isinstance(roles, Mapping) else None
    if not isinstance(runtime_snapshot, Mapping) or not isinstance(checker_binding, Mapping):
        raise ValueError("frozen Run or Checker binding is unavailable")
    checker_endpoint_path = Path(str(checker_binding.get("endpoint_path", ""))).resolve()
    checker_endpoint = _read(checker_endpoint_path, "frozen Checker endpoint")
    if checker_endpoint != endpoint:
        raise ValueError("original Checker attempt differs from frozen RoleHost")
    address = checker_endpoint.get("address")
    runtime_root = Path(str(address.get("runtime_root", ""))).resolve() if isinstance(
        address, Mapping
    ) else Path()
    wrapper = runtime_root / "ocr-slk.ps1"
    if not runtime_root.is_dir() or not wrapper.is_file():
        raise ValueError("managed OCRV runtime is unavailable")

    session_value = _command_json(
        _ocr_command(
            wrapper, "session", "show", "--json", "--repo",
            str(Path(str(envelope.get("payload", {}).get("repository", ""))).resolve()),
            str(identity.get("session_id", "")),
        ),
        run_command,
    )
    session_summary = session_value.get("summary")
    if not isinstance(session_summary, Mapping):
        raise ValueError("original OCRV Session cannot be inspected")
    session_record = Path(str(session_summary.get("file_path", ""))).resolve()
    state_root = session_record.parent.parent
    repository = Path(str(envelope.get("payload", {}).get("repository", ""))).resolve()
    binding, transition, preview = _validate_managed_target(
        runtime_root=runtime_root,
        repository=repository,
        state_root=state_root,
        source_execution=execution,
        source_selected=selected,
        candidate_commit=str(envelope.get("payload", {}).get("candidate", {}).get("commit", "")),
        new_budget=max_tokens_budget,
        runner=run_command,
    )
    old_capacity = original_request.get("capacity")
    if not isinstance(old_capacity, Mapping):
        raise ValueError("original OCRV capacity is unavailable")
    revision = {
        "schema_version": REVISION_SCHEMA,
        "reason": "TERMINAL_TOKEN_BUDGET_EXHAUSTED",
        "old": {name: old_capacity.get(name) for name in CAPACITY_FIELDS},
        "observed": {name: summary.get(name) for name in USAGE_FIELDS},
        "new": {
            "max_tokens": old_capacity.get("max_tokens"),
            "max_tokens_budget": max_tokens_budget,
            "timeout_minutes": old_capacity.get("timeout_minutes"),
        },
    }
    authorization = {
        "schema_version": AUTHORIZATION_SCHEMA,
        "authority": "OWNER",
        "decision": "APPROVED",
        "authorization_id": authorization_id,
        "source_thread_id": source_thread_id,
        "capacity_revision_sha256": canonical_json_sha256(revision),
        "ocrv_transition_sha256": canonical_json_sha256(transition),
        "runtime_config_binding_sha256": canonical_json_sha256(binding),
        "occurred_at": occurred_at,
    }
    stable_identity = "|".join(
        (
            run_id, message_id, str(d1_incomplete.get("event_id")),
            str(max_tokens_budget), transition["target_version"], authorization_id,
        )
    )
    recovery_invocation_id = str(uuid.uuid5(_PREPARATION_NAMESPACE, stable_identity))
    recovery_root = attempt / "resume-terminal-budget-checker" / recovery_invocation_id
    payload = envelope.get("payload")
    candidate = payload.get("candidate") if isinstance(payload, Mapping) else None
    base = {
        "method_version": runtime_snapshot.get("method_version"),
        "recovery_invocation_id": recovery_invocation_id,
        "run_id": run_id,
        "go_id": envelope.get("go_id"),
        "cell_id": envelope.get("cell_id"),
        "attempt": d1_incomplete.get("attempt"),
        "plan_revision": runtime_snapshot.get("plan_revision"),
        "runtime_revision": runtime_snapshot.get("runtime_revision"),
        "token_sequence": runtime_snapshot.get("token_sequence"),
        "worker_role_instance_id": envelope.get("sender_role_instance_id"),
        "checker_role_instance_id": envelope.get("receiver_role_instance_id"),
        "checker_endpoint_version": envelope.get("receiver_endpoint_version"),
        "checker_endpoint": checker_endpoint,
        "runtime_projection_path": str(projection_path),
        "runtime_projection_sha256": _sha256(projection_path),
        "candidate_repository": str(repository),
        "candidate_commit": candidate.get("commit") if isinstance(candidate, Mapping) else None,
        "candidate_parent": manifest_input.get("resolved_base"),
        "candidate_message_id": message_id,
        "payload_sha256": envelope.get("payload_sha256"),
        "candidate_submitted_event_id": candidate_event.get("event_id"),
        "transport_started_event_id": transport_event.get("event_id"),
        "commit_request_path": str(commit_path),
        "commit_request_sha256": _sha256(commit_path),
        "native_attempt_path": str(attempt),
        "raw_review_path": str(raw_path),
        "immutable_sha256": {
            name: _sha256(attempt / name)
            for name in (
                "endpoint.json", "envelope.json", "started.json", "ocrv-request.json",
                "completed.json", "ocrv-result.json",
            )
        } | {"raw_review": _sha256(raw_path)},
        "checker_credential_path": checker_binding.get("credential_path"),
        "state_command": role_host.get("state_command"),
        "transport_command": role_host.get("transport_command"),
        "result_path": str(recovery_root / "result.json"),
    }
    preflight_path = attempt / "ocrv-preflight.json"
    activity_path = attempt / "native-activity.json"
    request = {
        "schema_version": REQUEST_SCHEMA,
        **base,
        "d1_started_event_id": d1_started.get("event_id"),
        "d1_incomplete_event_id": d1_incomplete.get("event_id"),
        "ocrv_preflight_path": str(preflight_path),
        "ocrv_preflight_sha256": _sha256(preflight_path),
        "background_path": str(background_path),
        "background_sha256": _sha256(background_path),
        "native_activity_path": str(activity_path),
        "native_activity_sha256": _sha256(activity_path),
        "session_record_path": str(session_record),
        "session_record_sha256": _sha256(session_record),
        "ocrv_session": {
            "session_id": session_summary.get("session_id"),
            "repo_dir": session_summary.get("repo_dir"),
            "diff_commit": session_summary.get("diff_commit"),
            "model": session_summary.get("model"),
            "review_mode": session_summary.get("review_mode"),
            "start_time": session_summary.get("start_time"),
            "aborted": session_summary.get("aborted"),
            "selected_files": session_summary.get("selected_files"),
            "completed_files": session_summary.get("completed_files"),
        },
        "capacity_revision": revision,
        "ocrv_transition": transition,
        "runtime_config_binding": binding,
        "owner_authorization": authorization,
        "role_host_binding_path": str(role_host_path),
        "role_host_binding_sha256": _sha256(role_host_path),
        "recovery_root": str(recovery_root),
    }
    validate(request)
    loader = load_current_projection or wc._default_load_current_projection
    current = loader(run_id, list(request["state_command"]))
    current_runtime = current.get("runtime_snapshot")
    current_revision = current_runtime.get("runtime_revision") if isinstance(
        current_runtime, Mapping
    ) else None
    if current_revision != request["runtime_revision"]:
        wc._rebind_overwatcher_only_committed_boundary(
            request, projection, current, current_revision
        )
    destination.parent.mkdir(parents=True, exist_ok=True)
    wc._write_or_reuse_stable_request(destination, request)
    digest = _sha256(destination)
    return {
        "schema_version": PREPARATION_SCHEMA,
        "method_version": request["method_version"],
        "status": "CHECKER_TERMINAL_BUDGET_REQUEST_READY",
        "run_id": run_id,
        "cell_id": request["cell_id"],
        "candidate_commit": request["candidate_commit"],
        "parent_session_id": request["ocrv_session"]["session_id"],
        "target_ocrv_version": transition["target_version"],
        "target_rule_config_sha256": transition["target_rule_config_sha256"],
        "target_runtime_config_sha256": binding["target_sha256"],
        "target_preview": preview,
        "request_path": str(destination),
        "request_sha256": digest,
        "prepare_only_command": [
            *list(request["transport_command"]),
            "resume-terminal-budget-checker", "--request", str(destination),
            "--sha256", digest, "--prepare-only",
        ],
    }


def ocrv_runtime_config_sha256(binding: Mapping[str, Any], max_tokens_budget: int) -> str:
    """Reproduce OCRV's length-prefixed, non-secret runtime identity."""

    fields = (
        "protocol", str(binding.get("protocol", "")),
        "model", str(binding.get("model", "")),
        "host", str(binding.get("endpoint_host", "")),
        "language", str(binding.get("language", "")),
        "timeout", str(binding.get("timeout", "")),
        "concurrency", str(binding.get("concurrency", "")),
        "max_tokens_budget", str(max_tokens_budget),
    )
    digest = hashlib.sha256()
    for field in fields:
        encoded = field.encode("utf-8")
        digest.update(struct.pack(">Q", len(encoded)))
        digest.update(encoded)
    return digest.hexdigest()


def _ocrv_version_tuple(value: object) -> tuple[int, int, int] | None:
    if not isinstance(value, str):
        return None
    match = re.fullmatch(r"v(\d+)\.(\d+)\.(\d+)", value)
    return tuple(int(part) for part in match.groups()) if match else None


def _supports_verified_resume_lineage(value: object) -> bool:
    version = _ocrv_version_tuple(value)
    return bool(version and version >= (1, 12, 7))


def _coverage_identities(value: object) -> set[tuple[str, str, str]]:
    if not isinstance(value, list) or any(not isinstance(item, Mapping) for item in value):
        raise ValueError("OCRV coverage is not an object array")
    identities = {
        (str(item.get("item_id", "")), str(item.get("path", "")), str(item.get("fingerprint", "")))
        for item in value
    }
    if len(identities) != len(value) or any(not all(identity) for identity in identities):
        raise ValueError("OCRV coverage identity is missing or duplicated")
    return identities


def validate_resumed_child(
    parent_raw: Mapping[str, Any], child_raw: Mapping[str, Any], lineage: Mapping[str, Any],
    *, target_ocrv_version: str | None = None,
    target_rule_config_sha256: str | None = None,
    target_runtime_config_sha256: str | None = None,
) -> None:
    """Prove that OCRV created one truthful child Session for the same review input."""

    parent_manifest = parent_raw.get("manifest")
    child_manifest = child_raw.get("manifest")
    if not isinstance(parent_manifest, Mapping) or not isinstance(child_manifest, Mapping):
        raise ValueError("OCRV parent/child manifest is missing")
    parent_session = parent_raw.get("session_id")
    child_session = child_raw.get("session_id")
    expected_lineage = {
        "schema_version": "ocr.resume-lineage/v1",
        "parent_run_id": parent_session,
        "run_id": child_session,
        "source_provider": "dashscope-tokenplan",
        "source_model": "qwen3.8-max",
        "target_provider": "dashscope-tokenplan",
        "target_model": "qwen3.8-max",
    }
    parent_coverage = parent_manifest.get("coverage")
    child_coverage = child_manifest.get("coverage")
    if (
        not isinstance(parent_session, str)
        or not parent_session
        or not isinstance(child_session, str)
        or not child_session
        or child_session == parent_session
        or any(lineage.get(key) != value for key, value in expected_lineage.items())
        or child_manifest.get("schema_version") != "ocr.run-manifest/v1"
        or child_manifest.get("operation") != "review"
        or child_manifest.get("run_id") != child_session
        or child_manifest.get("parent_run_id") != parent_session
        or child_manifest.get("input") != parent_manifest.get("input")
        or child_manifest.get("repository") != parent_manifest.get("repository")
        or not isinstance(parent_coverage, Mapping)
        or not isinstance(child_coverage, Mapping)
        or _coverage_identities(child_coverage.get("selected"))
        != _coverage_identities(parent_coverage.get("selected"))
    ):
        raise ValueError("OCRV resume did not preserve the exact parent/child review identity")
    parent_execution = parent_manifest.get("execution")
    child_execution = child_manifest.get("execution")
    if (
        not isinstance(parent_execution, Mapping)
        or not isinstance(child_execution, Mapping)
        or child_execution.get("ocr_version")
        != (target_ocrv_version or parent_execution.get("ocr_version"))
        or any(child_execution.get(key) != parent_execution.get(key) for key in ("provider", "model"))
        or child_execution.get("rule_config_sha256")
        != (target_rule_config_sha256 or parent_execution.get("rule_config_sha256"))
        or child_execution.get("runtime_config_sha256")
        != (target_runtime_config_sha256 or parent_execution.get("runtime_config_sha256"))
    ):
        raise ValueError("OCRV resume changed the frozen provider, model, or rules")


def _read(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} is unavailable or invalid") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} is not an object")
    return value


def read_session_records(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    try:
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            if not line.strip():
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError("OCRV Session record is not an object")
            records.append(value)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("OCRV Session record is unavailable or invalid") from exc
    return records


def _positive_map(value: object, fields: set[str]) -> bool:
    return (
        isinstance(value, Mapping)
        and set(value) == fields
        and all(isinstance(value[name], int) and not isinstance(value[name], bool) and value[name] > 0
                for name in fields)
    )


def validate(request: Mapping[str, Any], *, consumed: bool = False) -> dict[str, Any]:
    """Validate immutable source evidence before the sealed Checker can resume."""

    from . import worker_completion as wc

    if set(request) != {"schema_version", *BASE_FIELDS, *EXTRA_FIELDS} or request.get(
        "schema_version"
    ) != REQUEST_SCHEMA:
        raise wc.CompletionError(
            "CHECKER_TERMINAL_BUDGET_REQUEST_INVALID", "terminal-budget request is not closed"
        )
    try:
        attempt = Path(str(request["native_attempt_path"])).resolve()
        recovery = Path(str(request["recovery_root"])).resolve()
        result_path = Path(str(request["result_path"])).resolve()
        immutable = request["immutable_sha256"]
        revision = request["capacity_revision"]
        authorization = request["owner_authorization"]
        ocrv_transition = request["ocrv_transition"]
        runtime_binding = request["runtime_config_binding"]
        session = request["ocrv_session"]
    except (KeyError, TypeError, ValueError) as exc:
        raise wc.CompletionError(
            "CHECKER_TERMINAL_BUDGET_REQUEST_INVALID", "terminal-budget identity is invalid"
        ) from exc
    if (
        recovery != attempt / "resume-terminal-budget-checker" / str(request["recovery_invocation_id"])
        or result_path != recovery / "result.json"
        or (recovery / "resume-consumed.json").exists() != consumed
        or not isinstance(immutable, Mapping)
        or set(immutable) != {
            "endpoint.json", "envelope.json", "started.json", "ocrv-request.json",
            "completed.json", "ocrv-result.json", "raw_review",
        }
        or any(not wc._exact_digest(value) for value in immutable.values())
    ):
        raise wc.CompletionError(
            "CHECKER_TERMINAL_BUDGET_REQUEST_INVALID", "terminal-budget request is already consumed or malformed"
        )

    correction = {
        "correction_id": str(request["recovery_invocation_id"]),
        "d1_started_event_id": request["d1_started_event_id"],
        "d1_incomplete_event_id": request["d1_incomplete_event_id"],
        "native_terminal_sha256": immutable["completed.json"],
        "native_result_sha256": immutable["ocrv-result.json"],
    }
    if not all(isinstance(correction[name], str) and correction[name]
               for name in ("correction_id", "d1_started_event_id", "d1_incomplete_event_id")):
        raise wc.CompletionError(
            "CHECKER_TERMINAL_BUDGET_REQUEST_INVALID", "source D1 identity is invalid"
        )
    source = {key: request[key] for key in BASE_FIELDS}
    source.update(
        schema_version=wc.COMMITTED_TERMINAL_SCHEMA,
        raw_review_path="unused",
        immutable_sha256={name: immutable[name] for name in (
            "endpoint.json", "envelope.json", "started.json", "ocrv-request.json"
        )},
    )
    try:
        common = wc._validate_committed_terminal_request(
            source, source_only=True, d1_correction=correction
        )
    except wc.CompletionError:
        raise
    except (KeyError, TypeError, ValueError) as exc:
        raise wc.CompletionError(
            "CHECKER_TERMINAL_BUDGET_EVIDENCE_INVALID", "committed Checker source is invalid"
        ) from exc

    paths = {
        "completed.json": attempt / "completed.json",
        "ocrv-result.json": attempt / "ocrv-result.json",
        "raw_review": Path(str(request["raw_review_path"])).resolve(),
        "ocrv-preflight.json": Path(str(request["ocrv_preflight_path"])).resolve(),
        "d1-background.md": Path(str(request["background_path"])).resolve(),
        "native-activity.json": Path(str(request["native_activity_path"])).resolve(),
        "session-record": Path(str(request["session_record_path"])).resolve(),
    }
    supplied_hashes = {
        "completed.json": immutable["completed.json"],
        "ocrv-result.json": immutable["ocrv-result.json"],
        "raw_review": immutable["raw_review"],
        "ocrv-preflight.json": request["ocrv_preflight_sha256"],
        "d1-background.md": request["background_sha256"],
        "native-activity.json": request["native_activity_sha256"],
        "session-record": request["session_record_sha256"],
    }
    if any(
        not wc._exact_digest(digest)
        or not path.is_file()
        or wc._sha256(path) != digest
        for name, path in paths.items()
        for digest in [supplied_hashes[name]]
    ):
        raise wc.CompletionError(
            "CHECKER_TERMINAL_BUDGET_EVIDENCE_INVALID", "terminal-budget evidence changed or is missing"
        )

    original_request = _read(attempt / "ocrv-request.json", "original OCRV request")
    preflight = _read(paths["ocrv-preflight.json"], "original OCRV preflight")
    activity = _read(paths["native-activity.json"], "original OCRV activity")
    terminal = _read(paths["completed.json"], "original OCRV terminal")
    result = _read(paths["ocrv-result.json"], "original OCRV result")
    raw = _read(paths["raw_review"], "original OCRV raw review")
    manifest = raw.get("manifest")
    summary = raw.get("summary")
    tools = raw.get("tool_calls")
    coverage = manifest.get("coverage") if isinstance(manifest, Mapping) else None
    manifest_input = manifest.get("input") if isinstance(manifest, Mapping) else None
    execution = manifest.get("execution") if isinstance(manifest, Mapping) else None
    selected = coverage.get("selected") if isinstance(coverage, Mapping) else None
    completed = coverage.get("completed") if isinstance(coverage, Mapping) else None
    reused = coverage.get("reused") if isinstance(coverage, Mapping) else None
    failed = coverage.get("failed") if isinstance(coverage, Mapping) else None
    waived = coverage.get("waived") if isinstance(coverage, Mapping) else None
    identity = terminal.get("native_identity")
    if (
        preflight.get("status") != "READY"
        or preflight.get("request_sha256") != immutable["ocrv-request.json"]
        or not wc._matches(preflight.get("background"), {"sha256": request["background_sha256"]})
        or activity.get("status") not in {"FAILED", "COMPLETED"}
        or activity.get("native_task_id") != result.get("review_invocation_id")
        or activity.get("waiting_on") is not None
        or terminal.get("status") != "completed"
        or terminal.get("error_code") is not None
        or not isinstance(identity, Mapping)
        or identity.get("verdict") != "INCOMPLETE"
        or identity.get("exit_code") != 3
        or identity.get("session_id") != result.get("review", {}).get("session_id")
        or result.get("verdict") != "INCOMPLETE"
        or result.get("review", {}).get("status") != "failed"
        or result.get("request_sha256") != immutable["ocrv-request.json"]
        or raw.get("status") != "failed"
        or not isinstance(summary, Mapping)
        or summary.get("budget_exceeded") is not True
        or not isinstance(tools, Mapping)
        or tools.get("failure") != 0
        or not isinstance(manifest, Mapping)
        or manifest.get("schema_version") != "ocr.run-manifest/v1"
        or manifest.get("operation") != "review"
        or manifest.get("terminal_state") != "failed"
        or not isinstance(manifest_input, Mapping)
        or manifest_input.get("resolved_base") != request["candidate_parent"]
        or manifest_input.get("resolved_head") != request["candidate_commit"]
        or manifest_input.get("exact_range")
        != f'{request["candidate_parent"]}..{request["candidate_commit"]}'
        or not isinstance(execution, Mapping)
        or not _supports_verified_resume_lineage(execution.get("ocr_version"))
        or execution.get("provider") != "dashscope-tokenplan"
        or execution.get("model") != "qwen3.8-max"
        or not isinstance(selected, list) or not selected
        or completed != [] or reused != [] or waived != []
        or not isinstance(failed, list) or len(failed) != len(selected)
        or {json.dumps(item, sort_keys=True) for item in selected}
        != {json.dumps({key: item.get(key) for key in ("item_id", "path", "fingerprint")}, sort_keys=True)
            for item in failed if isinstance(item, Mapping)}
        or any(not isinstance(item, Mapping) or item.get("classification") != "budget" for item in failed)
    ):
        raise wc.CompletionError(
            "CHECKER_TERMINAL_BUDGET_EVIDENCE_INVALID",
            "source terminal is not an ordinary budget-only incomplete review",
        )

    if (
        not isinstance(session, Mapping)
        or set(session) != {
            "session_id", "repo_dir", "diff_commit", "model", "review_mode",
            "start_time", "aborted", "selected_files", "completed_files",
        }
        or session.get("session_id") != raw.get("session_id")
        or Path(str(session.get("repo_dir", ""))).resolve()
        != Path(str(request["candidate_repository"])).resolve()
        or session.get("diff_commit") != request["candidate_commit"]
        or session.get("model") != "qwen3.8-max"
        or session.get("review_mode") != "commit"
        or not isinstance(session.get("start_time"), str)
        or not session["start_time"]
        or session.get("aborted") is not False
        or session.get("selected_files") != len(selected)
        or session.get("completed_files") != 0
    ):
        raise wc.CompletionError(
            "CHECKER_TERMINAL_BUDGET_EVIDENCE_INVALID", "OCRV Session identity is not exact"
        )

    old_capacity = original_request.get("capacity")
    old = revision.get("old") if isinstance(revision, Mapping) else None
    observed = revision.get("observed") if isinstance(revision, Mapping) else None
    new = revision.get("new") if isinstance(revision, Mapping) else None
    if (
        not isinstance(revision, Mapping)
        or set(revision) != {"schema_version", "reason", "old", "observed", "new"}
        or revision.get("schema_version") != REVISION_SCHEMA
        or revision.get("reason") != "TERMINAL_TOKEN_BUDGET_EXHAUSTED"
        or not _positive_map(old, CAPACITY_FIELDS)
        or not _positive_map(observed, USAGE_FIELDS)
        or not _positive_map(new, CAPACITY_FIELDS)
        or not isinstance(old_capacity, Mapping)
        or any(old[name] != old_capacity.get(name) for name in CAPACITY_FIELDS)
        or any(observed[name] != summary.get(name) for name in USAGE_FIELDS)
        or observed["total_tokens"] <= old["max_tokens_budget"]
        or new["max_tokens"] != old["max_tokens"]
        or new["timeout_minutes"] != old["timeout_minutes"]
        or new["max_tokens_budget"] <= old["max_tokens_budget"]
        or new["max_tokens_budget"] <= observed["total_tokens"]
    ):
        raise wc.CompletionError(
            "CHECKER_TERMINAL_BUDGET_CAPACITY_INVALID",
            "capacity revision is not a finite exact Owner-bound increase above observed use",
        )
    source_ocrv_version = execution.get("ocr_version")
    source_version_tuple = _ocrv_version_tuple(source_ocrv_version)
    target_version_tuple = (
        _ocrv_version_tuple(ocrv_transition.get("target_version"))
        if isinstance(ocrv_transition, Mapping)
        else None
    )
    if (
        not isinstance(ocrv_transition, Mapping)
        or set(ocrv_transition) != {
            "schema_version", "reason", "source_version", "target_version",
            "source_rule_config_sha256", "target_rule_config_sha256",
        }
        or ocrv_transition.get("schema_version") != OCRV_TRANSITION_SCHEMA
        or ocrv_transition.get("reason") != "OWNER_REQUESTED_TOOL_UNIFICATION"
        or ocrv_transition.get("source_version") != source_ocrv_version
        or ocrv_transition.get("source_rule_config_sha256") != execution.get("rule_config_sha256")
        or not wc._exact_digest(ocrv_transition.get("target_rule_config_sha256"))
        or source_version_tuple is None
        or target_version_tuple is None
        or target_version_tuple < (1, 12, 7)
        or target_version_tuple < source_version_tuple
    ):
        raise wc.CompletionError(
            "CHECKER_TERMINAL_BUDGET_OCRV_TRANSITION_INVALID",
            "OCRV source/target transition is absent, unsupported, or not monotonic",
        )
    if (
        not isinstance(runtime_binding, Mapping)
        or set(runtime_binding) != RUNTIME_CONFIG_FIELDS
        or runtime_binding.get("schema_version") != RUNTIME_CONFIG_BINDING_SCHEMA
        or runtime_binding.get("protocol") != "openai"
        or runtime_binding.get("model") != "qwen3.8-max"
        or not all(
            isinstance(runtime_binding.get(name), str)
            and runtime_binding[name]
            and runtime_binding[name] == runtime_binding[name].strip()
            for name in ("endpoint_host", "language", "timeout")
        )
        or isinstance(runtime_binding.get("concurrency"), bool)
        or not isinstance(runtime_binding.get("concurrency"), int)
        or runtime_binding["concurrency"] < 1
        or runtime_binding.get("source_sha256") != execution.get("runtime_config_sha256")
        or runtime_binding.get("source_sha256")
        != ocrv_runtime_config_sha256(runtime_binding, old["max_tokens_budget"])
        or runtime_binding.get("target_sha256")
        != ocrv_runtime_config_sha256(runtime_binding, new["max_tokens_budget"])
    ):
        raise wc.CompletionError(
            "CHECKER_TERMINAL_BUDGET_RUNTIME_CONFIG_INVALID",
            "OCRV runtime identity is not the exact source-to-target capacity binding",
        )
    role_host_raw = Path(str(request["role_host_binding_path"]))
    role_host_path = role_host_raw.resolve()
    if (
        not role_host_raw.is_absolute()
        or not wc._exact_digest(request["role_host_binding_sha256"])
        or not role_host_path.is_file()
        or wc._sha256(role_host_path) != request["role_host_binding_sha256"]
    ):
        raise wc.CompletionError(
            "CHECKER_TERMINAL_BUDGET_ROLE_HOST_INVALID",
            "the frozen RoleHost binding is unavailable or changed",
        )
    role_host = _read(role_host_path, "RoleHost binding")
    roles = role_host.get("roles")
    checker_binding = roles.get("checker") if isinstance(roles, Mapping) else None
    role_files_valid = isinstance(roles, Mapping)
    if role_files_valid:
        for role in ("supervisor", "checker", "worker"):
            item = roles.get(role)
            if not isinstance(item, Mapping) or set(item) != {
                "endpoint_path", "endpoint_sha256", "credential_path",
            }:
                role_files_valid = False
                break
            endpoint_raw = Path(str(item["endpoint_path"]))
            endpoint_path = endpoint_raw.resolve()
            if (
                not endpoint_raw.is_absolute()
                or not wc._exact_digest(item["endpoint_sha256"])
                or not endpoint_path.is_file()
                or wc._sha256(endpoint_path) != item["endpoint_sha256"]
            ):
                role_files_valid = False
                break
    if (
        role_host.get("schema_version") != "slk.role-host/v2"
        or role_host.get("run_id") != request["run_id"]
        or role_host.get("plan_revision") != request["plan_revision"]
        or role_host.get("state_command") != request["state_command"]
        or role_host.get("transport_command") != request["transport_command"]
        or not isinstance(roles, Mapping)
        or set(roles) != {"supervisor", "checker", "worker"}
        or not role_files_valid
        or not isinstance(checker_binding, Mapping)
        or checker_binding.get("credential_path") != request["checker_credential_path"]
        or _read(Path(str(checker_binding.get("endpoint_path"))), "RoleHost Checker endpoint")
        != request["checker_endpoint"]
        or not isinstance(role_host.get("cells"), list)
        or not role_host["cells"]
        or not isinstance(role_host.get("d2_criteria"), list)
        or not role_host["d2_criteria"]
    ):
        raise wc.CompletionError(
            "CHECKER_TERMINAL_BUDGET_ROLE_HOST_INVALID",
            "the frozen RoleHost binding does not match this Run and Checker",
        )
    if (
        not isinstance(authorization, Mapping)
        or set(authorization) != {
            "schema_version", "authority", "decision", "authorization_id",
            "source_thread_id", "capacity_revision_sha256", "ocrv_transition_sha256",
            "runtime_config_binding_sha256", "occurred_at",
        }
        or authorization.get("schema_version") != AUTHORIZATION_SCHEMA
        or authorization.get("authority") != "OWNER"
        or authorization.get("decision") != "APPROVED"
        or not all(isinstance(authorization.get(name), str) and authorization[name]
                   for name in ("authorization_id", "source_thread_id", "occurred_at"))
        or authorization.get("capacity_revision_sha256") != canonical_json_sha256(revision)
        or authorization.get("ocrv_transition_sha256")
        != canonical_json_sha256(ocrv_transition)
        or authorization.get("runtime_config_binding_sha256")
        != canonical_json_sha256(runtime_binding)
    ):
        raise wc.CompletionError(
            "CHECKER_TERMINAL_BUDGET_AUTHORIZATION_INVALID",
            "Owner capacity authorization is absent or does not bind the exact revision",
        )
    return {
        **common,
        "attempt": attempt,
        "recovery_root": recovery,
        "paths": paths,
        "session": dict(session),
        "capacity_revision": dict(revision),
        "owner_authorization": dict(authorization),
        "ocr_version": execution.get("ocr_version"),
        "target_ocrv_version": ocrv_transition["target_version"],
        "target_rule_config_sha256": ocrv_transition["target_rule_config_sha256"],
        "target_runtime_config_sha256": runtime_binding["target_sha256"],
        "role_host_binding": role_host,
        "d1_correction": correction,
    }
