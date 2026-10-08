"""Command-line entry point for the SLK transport artifact."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Mapping

from .adapters.base import Adapter, AdapterError
from .adapters.codex import CodexAdapter
from .adapters.dsh import DshAdapter
from .adapters.ocrv import OcrvAdapter
from .active_writer import recover_active_writer
from .checker_escalation import CheckerEscalationError, execute_checker_escalation
from .checker_management import execute_checker_management
from .context_review import prepare as prepare_context_review
from .checker_completion import CheckerCompletionError, execute_checker_completion
from .desktop_current_turn import (
    complete_desktop_current_turn,
    prepare_desktop_current_turn,
)
from .contracts import ContractError, Endpoint, Envelope, parse_delivery
from .dispatcher import dispatch_once
from .drill_verify import DrillVerificationError, verify_drill
from .evidence import Attempt
from .native_activity import NativeActivityError, inspect_native_activity, validate_native_start
from .overwatcher_desktop import attest_desktop_overwatcher, desktop_overwatcher_probe
from .process import windows_no_window_kwargs
from .recovery import inspect_delivery, retry_exact
from .role_eval import load_pack, pack_sha256, validate_response
from .run_readiness import (
    evaluate_conformance_sample_admission,
    evaluate_new_run_admission,
    evaluate_run_admission,
    evaluate_run_readiness,
    seal_normal_chain_source,
)
from .role_host import RoleHost, load_role_host
from .runtime_binding_migration import (
    execute_runtime_binding_migration,
    prepare_runtime_binding_migration,
)
from .overwatcher_admin import execute_sealed_overwatcher_admin
from .pre_start_rejection import execute_pre_start_rejection
from .supervisor_admin import execute_sealed_supervisor_admin
from .temporal_reload import reload_temporal_worker
from .terminal_budget import prepare_terminal_budget_request
from .terminal_budget_fresh import prepare_fresh_review_request
from .terminal_budget_fresh_partial import prepare_fresh_partial_request
from .overwatcher_continuity import OverwatcherContinuityError, inspect_overwatcher_cadence
from .worker_completion import (
    CompletionError,
    consume_committed_checker_terminal,
    consume_staged_checker_terminal,
    continuation_request_bytes,
    execute_committed_checker_terminal,
    execute_checker_recovery,
    execute_worker_continuation,
    inspect_worker_completion,
    prepare_invalid_result_recovery_envelope,
    prepare_pre_d0_blocked_recovery_envelope,
    prepare_incomplete_worker_handoff,
    recover_staged_checker_commit,
    continue_consumed_partial_checker,
    consume_existing_partial_checker,
    refine_consumed_partial_checker,
    resume_consumed_partial_checker,
    resume_incomplete_checker,
    resume_terminal_budget_checker,
    resume_terminal_budget_fresh_partial,
    resume_terminal_budget_fresh_partial_suffix,
    resume_terminal_budget_fresh_review,
)


VERSION = "4.4.2"
ADAPTERS: Mapping[str, Adapter] = {
    "codex-app-server": CodexAdapter(),
    "ocrv-checker": OcrvAdapter(),
    "dsh-worker": DshAdapter(),
}


def _read_object(path: Path, label: str) -> Mapping[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} is not readable JSON") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


def _load_delivery(endpoint_path: Path, envelope_path: Path) -> tuple[Endpoint, Envelope]:
    parsed = parse_delivery(
        _read_object(endpoint_path, "endpoint"),
        _read_object(envelope_path, "envelope"),
    )
    try:
        adapter = ADAPTERS[parsed.endpoint.adapter]
    except KeyError as exc:
        raise AdapterError("ADAPTER_UNAVAILABLE", "endpoint adapter is unavailable") from exc
    adapter.validate_address(parsed.endpoint)
    return parsed.endpoint, parsed.envelope


def _emit(value: Mapping[str, Any]) -> None:
    print(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")))


def _rejected(error_code: str, message: str) -> int:
    _emit({"status": "rejected", "error_code": error_code, "message": message})
    return 2


def _validate(args: argparse.Namespace) -> int:
    endpoint, envelope = _load_delivery(args.endpoint, args.envelope)
    _emit(
        {
            "status": "valid",
            "run_id": envelope.run_id,
            "message_id": envelope.message_id,
            "adapter": endpoint.adapter,
            "receiver_role_instance_id": endpoint.role_instance_id,
            "endpoint_version": endpoint.endpoint_version,
        }
    )
    return 0


def _job(args: argparse.Namespace) -> int:
    endpoint_raw = _read_object(args.endpoint, "endpoint")
    envelope_raw = _read_object(args.envelope, "envelope")
    host = load_role_host(endpoint_raw)
    result = dispatch_once(
        endpoint_raw,
        envelope_raw,
        args.attempt_root,
        adapters=ADAPTERS,
    )
    if host is not None:
        source = args.attempt_root / result.run_id / result.message_id
        try:
            host.complete(source)
        except (ValueError, OSError) as exc:
            # Engineering completion is immutable and is not handoff success.
            from .worker_completion import _write_or_reuse_stable_request
            root = source / "role-host"
            root.mkdir(parents=True, exist_ok=True)
            failure = {"status": "HOST_HANDOFF_FAILED", "run_id": result.run_id,
                       "source_message_id": result.message_id,
                       "error_code": getattr(exc, "error_code", type(exc).__name__)}
            _write_or_reuse_stable_request(root / f"failure-{failure['error_code']}.json", failure)
            raise
    _emit(result.to_dict())
    return 0 if result.status == "completed" else 3


def _self_command() -> list[str]:
    invoked = Path(sys.argv[0]).resolve()
    if invoked.suffix.lower() in {".pyz", ".pyzw"} and invoked.is_file():
        return [sys.executable, str(invoked)]
    return [sys.executable, "-m", "slk_transport.cli"]


def _spawn_send_job(
    command: list[str], *, stdout: Any, stderr: Any
) -> subprocess.Popen[Any]:
    """Start one headless job, falling back only when a containing Windows Job denies breakaway."""

    process_kwargs = windows_no_window_kwargs(detached=True)
    start_new_session = not process_kwargs

    def start(kwargs: Mapping[str, Any]) -> subprocess.Popen[Any]:
        return subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=stdout,
            stderr=stderr,
            close_fds=True,
            start_new_session=start_new_session,
            **kwargs,
        )

    try:
        return start(process_kwargs)
    except OSError as exc:
        breakaway = int(getattr(subprocess, "CREATE_BREAKAWAY_FROM_JOB", 0))
        flags = int(process_kwargs.get("creationflags", 0))
        if getattr(exc, "winerror", None) != 5 or not breakaway or not flags & breakaway:
            raise
        fallback = dict(process_kwargs)
        fallback["creationflags"] = flags & ~breakaway
        return start(fallback)


def _send(args: argparse.Namespace) -> int:
    endpoint, envelope = _load_delivery(args.endpoint, args.envelope)
    attempt_root = args.attempt_root.resolve()
    attempt_path = attempt_root / envelope.run_id / envelope.message_id
    job_log_root = attempt_root / ".jobs"
    job_log_root.mkdir(parents=True, exist_ok=True)
    stdout_path = job_log_root / f"{envelope.message_id}.stdout.txt"
    stderr_path = job_log_root / f"{envelope.message_id}.stderr.txt"
    command = _self_command() + [
        "job",
        "--endpoint",
        str(args.endpoint.resolve()),
        "--envelope",
        str(args.envelope.resolve()),
        "--attempt-root",
        str(attempt_root),
    ]
    with stdout_path.open("wb") as stdout, stderr_path.open("wb") as stderr:
        process = _spawn_send_job(command, stdout=stdout, stderr=stderr)
    deadline = time.monotonic() + args.startup_timeout_seconds
    while time.monotonic() < deadline:
        failed = attempt_path / "failed.json"
        completed = attempt_path / "completed.json"
        started = attempt_path / "started.json"
        if failed.is_file():
            value = _read_object(failed, "failed result")
            _emit({**value, "job_pid": process.pid})
            return 3
        if completed.is_file():
            value = _read_object(completed, "completed result")
            _emit({**value, "job_pid": process.pid})
            return 0
        if started.is_file():
            try:
                validate_native_start(
                    started,
                    adapter=endpoint.adapter,
                    run_id=envelope.run_id,
                    cell_id=envelope.cell_id,
                    message_id=envelope.message_id,
                )
            except NativeActivityError:
                if process.poll() is not None:
                    break
                time.sleep(0.02)
                continue
            _emit(
                {
                    "status": "started",
                    "run_id": envelope.run_id,
                    "message_id": envelope.message_id,
                    "adapter": endpoint.adapter,
                    "job_pid": process.pid,
                    "evidence": str(started),
                }
            )
            return 0
        if process.poll() is not None:
            break
        time.sleep(0.02)
    _emit(
        {
            "status": "not-started",
            "run_id": envelope.run_id,
            "message_id": envelope.message_id,
            "adapter": endpoint.adapter,
            "job_pid": process.pid,
            "error_code": "NATIVE_START_NOT_OBSERVED",
        }
    )
    return 4


def _drill_verify(args: argparse.Namespace) -> int:
    _emit(verify_drill(args.evidence_root))
    return 0


def _inspect(args: argparse.Namespace) -> int:
    endpoint = _read_object(args.endpoint, "endpoint")
    envelope = _read_object(args.envelope, "envelope")
    _load_delivery(args.endpoint, args.envelope)
    _emit(inspect_delivery(args.attempt_root, endpoint, envelope))
    return 0


def _retry_exact(args: argparse.Namespace) -> int:
    endpoint = _read_object(args.endpoint, "endpoint")
    envelope = _read_object(args.envelope, "envelope")
    _load_delivery(args.endpoint, args.envelope)
    result = retry_exact(
        args.attempt_root,
        endpoint,
        envelope,
        adapters=ADAPTERS,
    )
    _emit(result)
    return 0 if result["status"] in {"ALREADY_STARTED", "RETRY_COMPLETED"} else 3


def _recover_active_writer(args: argparse.Namespace) -> int:
    endpoint = _read_object(args.endpoint, "endpoint")
    envelope = _read_object(args.envelope, "envelope")
    _load_delivery(args.endpoint, args.envelope)
    _emit(recover_active_writer(args.attempt_root, endpoint, envelope))
    return 0


def _prepare_desktop_current_turn(args: argparse.Namespace) -> int:
    endpoint = _read_object(args.endpoint, "endpoint")
    envelope = _read_object(args.envelope, "envelope")
    _load_delivery(args.endpoint, args.envelope)
    _emit(prepare_desktop_current_turn(args.attempt_root, endpoint, envelope))
    return 0


def _complete_desktop_current_turn(args: argparse.Namespace) -> int:
    endpoint = _read_object(args.endpoint, "endpoint")
    envelope = _read_object(args.envelope, "envelope")
    receipt = _read_object(args.host_receipt, "Desktop host receipt")
    _load_delivery(args.endpoint, args.envelope)
    _emit(complete_desktop_current_turn(args.attempt_root, endpoint, envelope, receipt))
    return 0


def _inspect_worker_completion(args: argparse.Namespace) -> int:
    previous = _read_object(args.previous_inspection, "previous inspection") if args.previous_inspection else None
    result = inspect_worker_completion(
        args.source_attempt,
        _read_object(args.runtime_projection, "runtime projection"),
        observed_at=args.observed_at,
        cadence_seconds=args.cadence_seconds,
        previous_inspection=previous,
    )
    if args.output:
        encoded = continuation_request_bytes(result)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        try:
            with args.output.open("xb") as stream:
                stream.write(encoded)
        except FileExistsError as exc:
            if args.output.read_bytes() != encoded:
                raise CompletionError(
                    "WORKER_COMPLETION_INSPECTION_CONFLICT",
                    "immutable inspection output already exists with different content",
                ) from exc
    _emit(result)
    return 3 if result["status"] == "WORKER_COMPLETION_HANDOFF_MISSING" else 0


def _continue_worker(args: argparse.Namespace) -> int:
    data = args.request.read_bytes()
    if __import__("hashlib").sha256(data).hexdigest() != args.sha256:
        raise CompletionError("WORKER_CONTINUATION_REQUEST_MISMATCH", "continuation request hash mismatch")
    request = _read_object(args.request, "continuation request")
    result = execute_worker_continuation(request)
    destination = Path(str(request["continuation_result_path"]))
    destination.parent.mkdir(parents=True, exist_ok=True)
    encoded = continuation_request_bytes(result)
    if destination.exists() and destination.read_bytes() != encoded:
        raise CompletionError("WORKER_CONTINUATION_CONFLICT", "continuation result conflicts")
    if not destination.exists():
        temporary = destination.with_suffix(destination.suffix + ".tmp")
        temporary.write_bytes(encoded)
        temporary.replace(destination)
    _emit(result)
    return 0


def _checker_recover_worker(args: argparse.Namespace) -> int:
    data = args.request.read_bytes()
    digest = __import__("hashlib").sha256(data).hexdigest()
    if digest != args.sha256:
        raise CompletionError("CHECKER_RECOVERY_REQUEST_MISMATCH", "Checker recovery request hash mismatch")
    request = _read_object(args.request, "Checker recovery request")
    result = execute_checker_recovery(request, request_sha256=digest)
    destination = Path(str(request["result_path"]))
    encoded = continuation_request_bytes(result)
    if destination.exists() and destination.read_bytes() != encoded:
        raise CompletionError("CHECKER_RECOVERY_CONFLICT", "Checker recovery result conflicts")
    if not destination.exists():
        temporary = destination.with_suffix(destination.suffix + ".tmp")
        temporary.write_bytes(encoded)
        temporary.replace(destination)
    _emit(result)
    return 0


def _checker_record_committed_terminal(args: argparse.Namespace) -> int:
    data = args.request.read_bytes()
    digest = __import__("hashlib").sha256(data).hexdigest()
    if digest != args.sha256:
        raise CompletionError(
            "CHECKER_COMMITTED_TERMINAL_REQUEST_MISMATCH",
            "committed-terminal request hash mismatch",
        )
    request = _read_object(args.request, "committed-terminal request")
    result = execute_committed_checker_terminal(request, request_sha256=digest)
    destination = Path(str(request["result_path"]))
    encoded = continuation_request_bytes(result)
    if destination.exists() and destination.read_bytes() != encoded:
        raise CompletionError(
            "CHECKER_COMMITTED_TERMINAL_CONFLICT",
            "committed-terminal result conflicts",
        )
    if not destination.exists():
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_suffix(destination.suffix + ".tmp")
        temporary.write_bytes(encoded)
        temporary.replace(destination)
    _emit(result)
    return 0


def _prepare_invalid_result_recovery(args: argparse.Namespace) -> int:
    result = prepare_invalid_result_recovery_envelope(
        args.source_attempt,
        _read_object(args.checker_endpoint, "Checker endpoint"),
        args.runtime_projection,
        supervisor_role_instance_id=args.supervisor_role_instance_id,
        plan_revision=args.plan_revision,
        runtime_revision=args.runtime_revision,
        token_sequence=args.token_sequence,
        worker_credential_path=args.worker_credential,
        checker_credential_path=args.checker_credential,
        state_command=list(args.state_command),
        transport_command=list(args.transport_command),
        occurred_at=args.occurred_at,
        output_path=args.output,
    )
    _emit(result)
    return 0


def _prepare_pre_d0_blocked_recovery(args: argparse.Namespace) -> int:
    result = prepare_pre_d0_blocked_recovery_envelope(
        args.source_attempt,
        _read_object(args.checker_endpoint, "Checker endpoint"),
        args.runtime_projection,
        supervisor_role_instance_id=args.supervisor_role_instance_id,
        plan_revision=args.plan_revision,
        runtime_revision=args.runtime_revision,
        token_sequence=args.token_sequence,
        worker_credential_path=args.worker_credential,
        checker_credential_path=args.checker_credential,
        state_command=list(args.state_command),
        transport_command=list(args.transport_command),
        environment_adjustment_path=args.environment_adjustment,
        environment_adjustment_sha256=args.environment_adjustment_sha256,
        occurred_at=args.occurred_at,
        output_path=args.output,
    )
    _emit(result)
    return 0


def _recover_staged_checker_commit(args: argparse.Namespace) -> int:
    result = recover_staged_checker_commit(
        _read_object(args.continuation, "Worker continuation request"),
        _read_object(args.outcome, "staged Checker delivery result"),
        failed_request_path=args.failed_request,
    )
    _emit(result)
    return 0


def _consume_staged_checker_terminal(args: argparse.Namespace) -> int:
    _emit(
        consume_staged_checker_terminal(
            args.request,
            request_sha256=args.sha256,
        )
    )
    return 0


def _consume_committed_checker_terminal(args: argparse.Namespace) -> int:
    _emit(
        consume_committed_checker_terminal(
            args.request,
            request_sha256=args.sha256,
        )
    )
    return 0


def _resume_incomplete_checker(args: argparse.Namespace) -> int:
    _emit(resume_incomplete_checker(args.request, request_sha256=args.sha256, prepare_only=args.prepare_only))
    return 0


def _resume_terminal_budget_checker(args: argparse.Namespace) -> int:
    _emit(resume_terminal_budget_checker(
        args.request, request_sha256=args.sha256, prepare_only=args.prepare_only))
    return 0


def _prepare_terminal_budget_checker(args: argparse.Namespace) -> int:
    _emit(prepare_terminal_budget_request(
        args.native_attempt,
        args.role_host_binding,
        max_tokens_budget=args.max_tokens_budget,
        authorization_id=args.authorization_id,
        source_thread_id=args.source_thread_id,
        occurred_at=args.occurred_at,
        output_path=args.output,
    ))
    return 0


def _prepare_terminal_budget_fresh_review(args: argparse.Namespace) -> int:
    _emit(prepare_fresh_review_request(
        args.source_request,
        authorization_id=args.authorization_id,
        source_thread_id=args.source_thread_id,
        occurred_at=args.occurred_at,
        output_path=args.output,
    ))
    return 0


def _resume_terminal_budget_fresh_review(args: argparse.Namespace) -> int:
    _emit(resume_terminal_budget_fresh_review(
        args.request, request_sha256=args.sha256, prepare_only=args.prepare_only))
    return 0


def _prepare_terminal_budget_fresh_partial(args: argparse.Namespace) -> int:
    _emit(prepare_fresh_partial_request(
        args.fresh_request,
        max_tokens_budget=args.max_tokens_budget,
        authorization_id=args.authorization_id,
        source_thread_id=args.source_thread_id,
        occurred_at=args.occurred_at,
        output_path=args.output,
    ))
    return 0


def _resume_terminal_budget_fresh_partial(args: argparse.Namespace) -> int:
    _emit(resume_terminal_budget_fresh_partial(
        args.request, request_sha256=args.sha256, prepare_only=args.prepare_only))
    return 0


def _resume_terminal_budget_fresh_partial_suffix(args: argparse.Namespace) -> int:
    _emit(resume_terminal_budget_fresh_partial_suffix(
        args.request, request_sha256=args.sha256, prepare_only=args.prepare_only))
    return 0


def _continue_consumed_partial_checker(args: argparse.Namespace) -> int:
    _emit(continue_consumed_partial_checker(
        args.request, request_sha256=args.sha256, prepare_only=args.prepare_only))
    return 0


def _resume_consumed_partial_checker(args: argparse.Namespace) -> int:
    _emit(resume_consumed_partial_checker(
        args.request, request_sha256=args.sha256, prepare_only=args.prepare_only))
    return 0


def _refine_consumed_partial_checker(args: argparse.Namespace) -> int:
    _emit(refine_consumed_partial_checker(
        args.request, request_sha256=args.sha256, prepare_only=args.prepare_only))
    return 0


def _consume_existing_partial_checker(args: argparse.Namespace) -> int:
    _emit(consume_existing_partial_checker(
        args.request, request_sha256=args.sha256, evidence_root=args.evidence_root,
        prepare_only=args.prepare_only))
    return 0


def _inspect_overwatcher_cadence(args: argparse.Namespace) -> int:
    result = inspect_overwatcher_cadence(
        _read_object(args.runtime_projection, "runtime projection"),
        observed_at=args.observed_at,
    )
    _emit(result)
    return 3 if result["status"] in {"LATE", "CONTINUITY_UNPROVEN"} else 0


def _inspect_native_activity(args: argparse.Namespace) -> int:
    terminals = tuple(path for path in (args.completed, args.failed) if path is not None)
    supplied = (args.desktop_overwatcher_attestation, args.desktop_overwatcher_attestation_sha256)
    if (supplied[0] is None) != (supplied[1] is None):
        raise ValueError("Desktop Overwatcher attestation path and hash must be supplied together")
    native_probe = None
    if supplied[0] is not None:
        native_probe = lambda start: desktop_overwatcher_probe(
            supplied[0], attestation_sha256=supplied[1], started_path=args.started, start=start,
        )
    result = inspect_native_activity(args.started, terminal_paths=terminals, native_probe=native_probe)
    _emit(result)
    return 0 if result["status"] in {"ACTIVE", "IDLE", "PENDING", "COMPLETED", "FAILED"} else 3


def _attest_desktop_overwatcher(args: argparse.Namespace) -> int:
    _emit(attest_desktop_overwatcher(
        args.request, request_sha256=args.sha256, evidence_root=args.evidence_root,
    ))
    return 0


def _notify_supervisor(args: argparse.Namespace) -> int:
    from .supervisor_notification import notify_registered_supervisor, notify_temporal_supervisor
    request = _read_object(args.request, "operational notification")
    if set(request) != {"notification", "endpoint_path", "runtime_projection_path", "attempt_root"}:
        raise ValueError("operational notification request is not closed")
    endpoint = _read_object(Path(request["endpoint_path"]), "registered Supervisor endpoint")
    projection = _read_object(Path(request["runtime_projection_path"]), "current Run projection")
    root = Path(request["attempt_root"])
    if not root.is_absolute():
        raise ValueError("operational notification evidence root must be absolute")
    value = request["notification"]
    if not isinstance(value, Mapping):
        raise ValueError("operational notification must be an object")
    notify = notify_registered_supervisor if "schema_version" in value else notify_temporal_supervisor
    _emit(notify(value, endpoint, projection, root))
    return 0


def _preflight_run(args: argparse.Namespace) -> int:
    result = evaluate_run_readiness(_read_object(args.request, "Run readiness request"))
    _emit(result)
    return 0 if result["status"] == "READY" else 3


def _preflight_admission(args: argparse.Namespace) -> int:
    result = evaluate_run_admission(_read_object(args.request, "Run admission request"))
    _emit(result)
    return 0 if result["status"] == "READY" else 3


def _seal_normal_chain_source(args: argparse.Namespace) -> int:
    _emit(seal_normal_chain_source(args.readiness_request, args.state_config, args.output))
    return 0


def _preflight_new_run(args: argparse.Namespace) -> int:
    result = evaluate_new_run_admission(_read_object(args.request, "new Run admission request"))
    _emit(result)
    return 0 if result["status"] == "READY" else 3


def _preflight_conformance_sample(args: argparse.Namespace) -> int:
    result = evaluate_conformance_sample_admission(
        _read_object(args.request, "conformance sample admission request"))
    _emit(result)
    return 0 if result["status"] == "READY" else 3


def _resume_role_host(args: argparse.Namespace) -> int:
    binding_path = args.binding.resolve()
    source = args.source_attempt.resolve()
    digest = hashlib.sha256(binding_path.read_bytes()).hexdigest()
    if digest != args.sha256:
        raise ValueError("role host binding hash changed")
    host = RoleHost(_read_object(binding_path, "role host binding"), digest)
    _emit(host.complete(source))
    return 0


def _reclassify_completed_checker(args: argparse.Namespace) -> int:
    binding_path = args.binding.resolve()
    digest = hashlib.sha256(binding_path.read_bytes()).hexdigest()
    if digest != args.sha256:
        raise ValueError("role host binding hash changed")
    host = RoleHost(_read_object(binding_path, "role host binding"), digest)
    _emit(host.reclassify_completed_checker(args.source_attempt.resolve()))
    return 0


def _consume_context_terminal(args: argparse.Namespace) -> int:
    path = args.binding.resolve()
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != args.sha256:
        raise ValueError('role host binding hash changed')
    host = RoleHost(_read_object(path, 'role host binding'), digest)
    _emit(host.consume_context_terminal(args.source_attempt.resolve(), args.session_record.resolve(),
                                        args.session_sha256, prepare_only=args.prepare_only))
    return 0


def _continue_staged_handoff(args: argparse.Namespace) -> int:
    binding_path = args.binding.resolve()
    digest = hashlib.sha256(binding_path.read_bytes()).hexdigest()
    if digest != args.sha256:
        raise ValueError("role host binding hash changed")
    host = RoleHost(_read_object(binding_path, "role host binding"), digest)
    _emit(host.continue_staged_handoff(
        args.source_attempt.resolve(),
        temporal_request_path=(args.temporal_request.resolve() if args.temporal_request else None),
        temporal_request_sha256=args.temporal_request_sha256,
    ))
    return 0


def _submit_supervisor_decision(args: argparse.Namespace) -> int:
    binding_path = args.binding.resolve()
    digest = hashlib.sha256(binding_path.read_bytes()).hexdigest()
    if digest != args.sha256:
        raise ValueError("role host binding hash changed")
    host = RoleHost(_read_object(binding_path, "role host binding"), digest)
    _emit(host.submit_supervisor_decision(args.source_attempt.resolve()))
    return 0


def _consume_desktop_readback(args: argparse.Namespace) -> int:
    from .adapters.codex_desktop import consume_desktop_readback

    source = args.source_attempt.resolve()
    parsed = parse_delivery(
        _read_object(source / "endpoint.json", "source endpoint"),
        _read_object(source / "envelope.json", "source envelope"),
    )
    result = consume_desktop_readback(parsed.endpoint, parsed.envelope, Attempt(source))
    _emit(result.to_dict())
    return 0 if result.status in {"completed", "started"} else 3


def _supervisor_admin(args: argparse.Namespace) -> int:
    _emit(execute_sealed_supervisor_admin(args.request, request_sha256=args.sha256))
    return 0


def _overwatcher_admin(args: argparse.Namespace) -> int:
    _emit(execute_sealed_overwatcher_admin(args.request, request_sha256=args.sha256))
    return 0


def _reload_temporal_worker(args: argparse.Namespace) -> int:
    _emit(reload_temporal_worker(args.request, request_sha256=args.sha256))
    return 0


def _prepare_runtime_binding_migration(args: argparse.Namespace) -> int:
    _emit(prepare_runtime_binding_migration(args.request, request_sha256=args.sha256))
    return 0


def _migrate_runtime_binding(args: argparse.Namespace) -> int:
    result = execute_runtime_binding_migration(args.request, request_sha256=args.sha256)
    _emit(result)
    return 0


def _abandon_pre_start_rejection(args: argparse.Namespace) -> int:
    _emit(execute_pre_start_rejection(args.request, request_sha256=args.sha256))
    return 0


def _prepare_role_credential(args: argparse.Namespace) -> int:
    from .worker_completion import prepare_sealed_role_credential

    request = _read_object(args.request, "role credential preparation")
    if set(request) != {"source", "destination", "run_id", "role", "role_instance_id", "state_command"}:
        raise ValueError("credential preparation requires the exact field set")
    _emit(prepare_sealed_role_credential(**request))
    return 0


def _validate_role_eval(args: argparse.Namespace) -> int:
    pack = load_pack(args.pack)
    if args.check_pack:
        result = {
            "status": "PASS",
            "case_count": len(pack["cases"]),
            "case_pack_sha256": pack_sha256(args.pack),
        }
    else:
        if not all(
            [args.response, args.run_id, args.project_id, args.plan_revision, args.role]
        ):
            raise ValueError(
                "role Eval response validation requires frozen Run, project, plan, and role"
            )
        result = validate_response(
            args.pack,
            _read_object(args.response, "role Eval response"),
            expected_run_id=args.run_id,
            expected_project_id=args.project_id,
            expected_plan_revision=args.plan_revision,
            expected_role=args.role,
        )
    _emit(result)
    return 0


def _checker_escalate_d1(args: argparse.Namespace) -> int:
    request = _read_object(args.request, "Checker post-D1 request")
    result = execute_checker_escalation(
        request,
        request_sha256=args.sha256,
        request_path=args.request,
        host_receipt_path=args.host_receipt,
    )
    _emit(result)
    return 0


def _checker_manage_incomplete(args: argparse.Namespace) -> int:
    request = _read_object(args.request, "Checker management request")
    result = execute_checker_management(
        request,
        request_sha256=args.sha256,
        request_path=args.request,
        host_receipt_path=args.host_receipt,
    )
    _emit(result)
    return 0


def _checker_complete_d1(args: argparse.Namespace) -> int:
    request = _read_object(args.request, "Checker completion request")
    result = execute_checker_completion(
        request,
        request_sha256=args.sha256,
        request_path=args.request,
        host_receipt_path=args.host_receipt,
    )
    _emit(result)
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="slk-transport")
    parser.add_argument("--version", action="version", version=f"slk-transport {VERSION}")
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name in (
        "validate",
        "job",
        "send",
        "inspect",
        "retry-exact",
        "recover-active-writer",
        "prepare-desktop-current-turn",
        "complete-desktop-current-turn",
    ):
        command = subparsers.add_parser(name)
        command.add_argument("--endpoint", required=True, type=Path)
        command.add_argument("--envelope", required=True, type=Path)
        if name in {
            "job",
            "send",
            "inspect",
            "retry-exact",
            "recover-active-writer",
            "prepare-desktop-current-turn",
            "complete-desktop-current-turn",
        }:
            command.add_argument("--attempt-root", required=True, type=Path)
        if name == "send":
            command.add_argument("--startup-timeout-seconds", type=float, default=30.0)
        if name == "complete-desktop-current-turn":
            command.add_argument("--host-receipt", required=True, type=Path)
    drill_verify = subparsers.add_parser("drill-verify")
    drill_verify.add_argument("--evidence-root", required=True, type=Path)
    completion = subparsers.add_parser("inspect-worker-completion")
    completion.add_argument("--source-attempt", required=True, type=Path)
    completion.add_argument("--runtime-projection", required=True, type=Path)
    completion.add_argument("--observed-at", required=True)
    completion.add_argument("--cadence-seconds", required=True, type=int)
    completion.add_argument("--previous-inspection", type=Path)
    completion.add_argument("--output", type=Path)
    checker_recovery = subparsers.add_parser("checker-recover-worker")
    checker_recovery.add_argument("--request", required=True, type=Path)
    checker_recovery.add_argument("--sha256", required=True)
    committed_checker = subparsers.add_parser("checker-record-committed-terminal")
    committed_checker.add_argument("--request", required=True, type=Path)
    committed_checker.add_argument("--sha256", required=True)
    invalid_result_recovery = subparsers.add_parser("prepare-invalid-result-recovery")
    invalid_result_recovery.add_argument("--source-attempt", required=True, type=Path)
    invalid_result_recovery.add_argument("--checker-endpoint", required=True, type=Path)
    invalid_result_recovery.add_argument("--runtime-projection", required=True, type=Path)
    invalid_result_recovery.add_argument("--supervisor-role-instance-id", required=True)
    invalid_result_recovery.add_argument("--plan-revision", required=True, type=int)
    invalid_result_recovery.add_argument("--runtime-revision", required=True, type=int)
    invalid_result_recovery.add_argument("--token-sequence", required=True, type=int)
    invalid_result_recovery.add_argument("--worker-credential", required=True, type=Path)
    invalid_result_recovery.add_argument("--checker-credential", required=True, type=Path)
    invalid_result_recovery.add_argument("--state-command", required=True, nargs="+")
    invalid_result_recovery.add_argument("--transport-command", required=True, nargs="+")
    invalid_result_recovery.add_argument("--occurred-at", required=True)
    invalid_result_recovery.add_argument("--output", required=True, type=Path)
    pre_d0_recovery = subparsers.add_parser("prepare-pre-d0-blocked-recovery")
    pre_d0_recovery.add_argument("--source-attempt", required=True, type=Path)
    pre_d0_recovery.add_argument("--checker-endpoint", required=True, type=Path)
    pre_d0_recovery.add_argument("--runtime-projection", required=True, type=Path)
    pre_d0_recovery.add_argument("--supervisor-role-instance-id", required=True)
    pre_d0_recovery.add_argument("--plan-revision", required=True, type=int)
    pre_d0_recovery.add_argument("--runtime-revision", required=True, type=int)
    pre_d0_recovery.add_argument("--token-sequence", required=True, type=int)
    pre_d0_recovery.add_argument("--worker-credential", required=True, type=Path)
    pre_d0_recovery.add_argument("--checker-credential", required=True, type=Path)
    pre_d0_recovery.add_argument("--state-command", required=True, nargs="+")
    pre_d0_recovery.add_argument("--transport-command", required=True, nargs="+")
    pre_d0_recovery.add_argument("--environment-adjustment", required=True, type=Path)
    pre_d0_recovery.add_argument("--environment-adjustment-sha256", required=True)
    pre_d0_recovery.add_argument("--occurred-at", required=True)
    pre_d0_recovery.add_argument("--output", required=True, type=Path)
    commit_recovery = subparsers.add_parser("recover-staged-checker-commit")
    commit_recovery.add_argument("--continuation", required=True, type=Path)
    commit_recovery.add_argument("--outcome", required=True, type=Path)
    commit_recovery.add_argument("--failed-request", required=True, type=Path)
    terminal_consumer = subparsers.add_parser("consume-staged-checker-terminal")
    terminal_consumer.add_argument("--request", required=True, type=Path)
    terminal_consumer.add_argument("--sha256", required=True)
    committed_consumer = subparsers.add_parser("consume-committed-checker-terminal")
    committed_consumer.add_argument("--request", required=True, type=Path)
    committed_consumer.add_argument("--sha256", required=True)
    incomplete_consumer = subparsers.add_parser("resume-incomplete-checker")
    incomplete_consumer.add_argument("--request", required=True, type=Path)
    incomplete_consumer.add_argument("--sha256", required=True)
    incomplete_consumer.add_argument("--prepare-only", action="store_true")
    terminal_budget_preparer = subparsers.add_parser("prepare-terminal-budget-checker")
    terminal_budget_preparer.add_argument("--native-attempt", required=True, type=Path)
    terminal_budget_preparer.add_argument("--role-host-binding", required=True, type=Path)
    terminal_budget_preparer.add_argument("--max-tokens-budget", required=True, type=int)
    terminal_budget_preparer.add_argument("--authorization-id", required=True)
    terminal_budget_preparer.add_argument("--source-thread-id", required=True)
    terminal_budget_preparer.add_argument("--occurred-at", required=True)
    terminal_budget_preparer.add_argument("--output", required=True, type=Path)
    context_preparer = subparsers.add_parser("prepare-context-review")
    for name in ("source-request", "source-result", "raw-review", "session-record", "output"):
        context_preparer.add_argument("--" + name, required=True, type=Path)
    context_preparer.add_argument("--candidate-message-id", required=True)
    context_preparer.add_argument("--source-d1-incomplete-event-id", required=True)
    context_preparer.add_argument("--per-file", action="store_true")
    context_preparer.add_argument("--per-call-input-threshold", action="store_true")
    context_terminal = subparsers.add_parser('consume-context-terminal')
    for name in ('binding', 'source-attempt', 'session-record'):
        context_terminal.add_argument('--' + name, required=True, type=Path)
    for name in ('sha256', 'session-sha256'):
        context_terminal.add_argument('--' + name, required=True)
    context_terminal.add_argument('--prepare-only', action='store_true')
    terminal_budget = subparsers.add_parser("resume-terminal-budget-checker")
    terminal_budget.add_argument("--request", required=True, type=Path)
    terminal_budget.add_argument("--sha256", required=True)
    terminal_budget.add_argument("--prepare-only", action="store_true")
    fresh_budget_preparer = subparsers.add_parser("prepare-terminal-budget-fresh-review")
    fresh_budget_preparer.add_argument("--source-request", required=True, type=Path)
    fresh_budget_preparer.add_argument("--authorization-id", required=True)
    fresh_budget_preparer.add_argument("--source-thread-id", required=True)
    fresh_budget_preparer.add_argument("--occurred-at", required=True)
    fresh_budget_preparer.add_argument("--output", required=True, type=Path)
    fresh_budget = subparsers.add_parser("resume-terminal-budget-fresh-review")
    fresh_budget.add_argument("--request", required=True, type=Path)
    fresh_budget.add_argument("--sha256", required=True)
    fresh_budget.add_argument("--prepare-only", action="store_true")
    fresh_partial_preparer = subparsers.add_parser("prepare-terminal-budget-fresh-partial")
    fresh_partial_preparer.add_argument("--fresh-request", required=True, type=Path)
    fresh_partial_preparer.add_argument("--max-tokens-budget", required=True, type=int)
    fresh_partial_preparer.add_argument("--authorization-id", required=True)
    fresh_partial_preparer.add_argument("--source-thread-id", required=True)
    fresh_partial_preparer.add_argument("--occurred-at", required=True)
    fresh_partial_preparer.add_argument("--output", required=True, type=Path)
    fresh_partial = subparsers.add_parser("resume-terminal-budget-fresh-partial")
    fresh_partial.add_argument("--request", required=True, type=Path)
    fresh_partial.add_argument("--sha256", required=True)
    fresh_partial.add_argument("--prepare-only", action="store_true")
    fresh_partial_suffix = subparsers.add_parser(
        "resume-terminal-budget-fresh-partial-suffix"
    )
    fresh_partial_suffix.add_argument("--request", required=True, type=Path)
    fresh_partial_suffix.add_argument("--sha256", required=True)
    fresh_partial_suffix.add_argument("--prepare-only", action="store_true")
    consumed_partial = subparsers.add_parser("continue-consumed-partial")
    consumed_partial.add_argument("--request", required=True, type=Path)
    consumed_partial.add_argument("--sha256", required=True)
    consumed_partial.add_argument("--prepare-only", action="store_true")
    resumed_partial = subparsers.add_parser("resume-consumed-partial")
    resumed_partial.add_argument("--request", required=True, type=Path)
    resumed_partial.add_argument("--sha256", required=True)
    resumed_partial.add_argument("--prepare-only", action="store_true")
    refined_partial = subparsers.add_parser("refine-consumed-partial")
    refined_partial.add_argument("--request", required=True, type=Path)
    refined_partial.add_argument("--sha256", required=True)
    refined_partial.add_argument("--prepare-only", action="store_true")
    existing_partial = subparsers.add_parser("consume-existing-partial")
    existing_partial.add_argument("--request", required=True, type=Path)
    existing_partial.add_argument("--sha256", required=True)
    existing_partial.add_argument("--evidence-root", required=True, type=Path)
    existing_partial.add_argument("--prepare-only", action="store_true")
    checker_escalation = subparsers.add_parser("checker-escalate-d1")
    checker_escalation.add_argument("--request", required=True, type=Path)
    checker_escalation.add_argument("--sha256", required=True)
    checker_escalation.add_argument("--host-receipt", type=Path)
    checker_management = subparsers.add_parser("checker-manage-incomplete")
    checker_management.add_argument("--request", required=True, type=Path)
    checker_management.add_argument("--sha256", required=True)
    checker_management.add_argument("--host-receipt", type=Path)
    checker_completion = subparsers.add_parser("checker-complete-d1")
    checker_completion.add_argument("--request", required=True, type=Path)
    checker_completion.add_argument("--sha256", required=True)
    checker_completion.add_argument("--host-receipt", type=Path)
    cadence = subparsers.add_parser("inspect-overwatcher-cadence")
    cadence.add_argument("--runtime-projection", required=True, type=Path)
    cadence.add_argument("--observed-at", required=True)
    native_activity = subparsers.add_parser("inspect-native-activity")
    native_activity.add_argument("--started", required=True, type=Path)
    native_activity.add_argument("--completed", type=Path)
    native_activity.add_argument("--failed", type=Path)
    native_activity.add_argument("--desktop-overwatcher-attestation", type=Path)
    native_activity.add_argument("--desktop-overwatcher-attestation-sha256")
    ow_desktop = subparsers.add_parser("attest-desktop-overwatcher")
    ow_desktop.add_argument("--request", required=True, type=Path)
    ow_desktop.add_argument("--sha256", required=True)
    ow_desktop.add_argument("--evidence-root", required=True, type=Path)
    notice = subparsers.add_parser("notify-supervisor")
    notice.add_argument("--request", required=True, type=Path)
    continuation = subparsers.add_parser("continue-worker")
    continuation.add_argument("--request", required=True, type=Path)
    continuation.add_argument("--sha256", required=True)
    readiness = subparsers.add_parser("preflight-run")
    readiness.add_argument("--request", required=True, type=Path)
    admission = subparsers.add_parser("preflight-admission")
    admission.add_argument("--request", required=True, type=Path)
    seal_source = subparsers.add_parser("seal-normal-chain-source")
    seal_source.add_argument("--readiness-request", required=True, type=Path)
    seal_source.add_argument("--state-config", required=True, type=Path)
    seal_source.add_argument("--output", required=True, type=Path)
    new_run = subparsers.add_parser("preflight-new-run")
    new_run.add_argument("--request", required=True, type=Path)
    conformance_sample = subparsers.add_parser("preflight-conformance-sample")
    conformance_sample.add_argument("--request", required=True, type=Path)
    role_host_resume = subparsers.add_parser("resume-role-host")
    role_host_resume.add_argument("--binding", required=True, type=Path)
    role_host_resume.add_argument("--sha256", required=True)
    role_host_resume.add_argument("--source-attempt", required=True, type=Path)
    reclassify_checker = subparsers.add_parser("reclassify-completed-checker")
    reclassify_checker.add_argument("--binding", required=True, type=Path)
    reclassify_checker.add_argument("--sha256", required=True)
    reclassify_checker.add_argument("--source-attempt", required=True, type=Path)
    staged_handoff = subparsers.add_parser("continue-staged-handoff")
    staged_handoff.add_argument("--binding", required=True, type=Path)
    staged_handoff.add_argument("--sha256", required=True)
    staged_handoff.add_argument("--source-attempt", required=True, type=Path)
    staged_handoff.add_argument("--temporal-request", type=Path)
    staged_handoff.add_argument("--temporal-request-sha256")
    supervisor_submit = subparsers.add_parser("submit-supervisor-decision")
    supervisor_submit.add_argument("--binding", required=True, type=Path)
    supervisor_submit.add_argument("--sha256", required=True)
    supervisor_submit.add_argument("--source-attempt", required=True, type=Path)
    desktop_readback = subparsers.add_parser("consume-desktop-readback")
    desktop_readback.add_argument("--source-attempt", required=True, type=Path)
    supervisor_admin = subparsers.add_parser("supervisor-admin")
    supervisor_admin.add_argument("--request", required=True, type=Path)
    supervisor_admin.add_argument("--sha256", required=True)
    overwatcher_admin = subparsers.add_parser("overwatcher-admin")
    overwatcher_admin.add_argument("--request", required=True, type=Path)
    overwatcher_admin.add_argument("--sha256", required=True)
    temporal_reload = subparsers.add_parser("reload-temporal-worker")
    temporal_reload.add_argument("--request", required=True, type=Path)
    temporal_reload.add_argument("--sha256", required=True)
    binding_preparation = subparsers.add_parser("prepare-runtime-binding-migration")
    binding_preparation.add_argument("--request", required=True, type=Path)
    binding_preparation.add_argument("--sha256", required=True)
    binding_migration = subparsers.add_parser("migrate-runtime-binding")
    binding_migration.add_argument("--request", required=True, type=Path)
    binding_migration.add_argument("--sha256", required=True)
    pre_start_rejection = subparsers.add_parser("abandon-pre-start-rejection")
    pre_start_rejection.add_argument("--request", required=True, type=Path)
    pre_start_rejection.add_argument("--sha256", required=True)
    credentials = subparsers.add_parser("prepare-role-credential")
    credentials.add_argument("--request", required=True, type=Path)
    incomplete = subparsers.add_parser("prepare-incomplete-handoff")
    incomplete.add_argument("--source-attempt", required=True, type=Path)
    incomplete.add_argument("--staged-envelope", required=True, type=Path)
    incomplete.add_argument("--d0-request", required=True, type=Path)
    role_eval = subparsers.add_parser("validate-role-eval")
    role_eval.add_argument("--pack", required=True, type=Path)
    role_eval.add_argument("--response", type=Path)
    role_eval.add_argument("--run-id")
    role_eval.add_argument("--project-id")
    role_eval.add_argument("--plan-revision", type=int)
    role_eval.add_argument("--role", choices=("supervisor", "checker", "worker", "overwatcher"))
    role_eval.add_argument("--check-pack", action="store_true")
    args = parser.parse_args(argv)
    if getattr(args, "startup_timeout_seconds", 1) <= 0:
        return _rejected("CLI_ARGUMENT_INVALID", "startup timeout must be positive")
    try:
        if args.command == 'consume-context-terminal':
            return _consume_context_terminal(args)
        if args.command == "validate":
            return _validate(args)
        if args.command == "job":
            return _job(args)
        if args.command == "send":
            return _send(args)
        if args.command == "drill-verify":
            return _drill_verify(args)
        if args.command == "inspect":
            return _inspect(args)
        if args.command == "retry-exact":
            return _retry_exact(args)
        if args.command == "recover-active-writer":
            return _recover_active_writer(args)
        if args.command == "prepare-desktop-current-turn":
            return _prepare_desktop_current_turn(args)
        if args.command == "complete-desktop-current-turn":
            return _complete_desktop_current_turn(args)
        if args.command == "inspect-worker-completion":
            return _inspect_worker_completion(args)
        if args.command == "checker-recover-worker":
            return _checker_recover_worker(args)
        if args.command == "checker-record-committed-terminal":
            return _checker_record_committed_terminal(args)
        if args.command == "prepare-invalid-result-recovery":
            return _prepare_invalid_result_recovery(args)
        if args.command == "prepare-pre-d0-blocked-recovery":
            return _prepare_pre_d0_blocked_recovery(args)
        if args.command == "recover-staged-checker-commit":
            return _recover_staged_checker_commit(args)
        if args.command == "consume-staged-checker-terminal":
            return _consume_staged_checker_terminal(args)
        if args.command == "consume-committed-checker-terminal":
            return _consume_committed_checker_terminal(args)
        if args.command == "resume-incomplete-checker":
            return _resume_incomplete_checker(args)
        if args.command == "prepare-terminal-budget-checker":
            return _prepare_terminal_budget_checker(args)
        if args.command == "prepare-context-review":
            _emit(prepare_context_review(
                source_request=args.source_request, source_result=args.source_result,
                raw_review=args.raw_review, session_record=args.session_record,
                candidate_message_id=args.candidate_message_id,
                source_d1_incomplete_event_id=args.source_d1_incomplete_event_id, output=args.output, per_file=args.per_file,
                per_call_input_threshold=args.per_call_input_threshold,
            ))
            return 0
        if args.command == "resume-terminal-budget-checker":
            return _resume_terminal_budget_checker(args)
        if args.command == "prepare-terminal-budget-fresh-review":
            return _prepare_terminal_budget_fresh_review(args)
        if args.command == "resume-terminal-budget-fresh-review":
            return _resume_terminal_budget_fresh_review(args)
        if args.command == "prepare-terminal-budget-fresh-partial":
            return _prepare_terminal_budget_fresh_partial(args)
        if args.command == "resume-terminal-budget-fresh-partial":
            return _resume_terminal_budget_fresh_partial(args)
        if args.command == "resume-terminal-budget-fresh-partial-suffix":
            return _resume_terminal_budget_fresh_partial_suffix(args)
        if args.command == "continue-consumed-partial":
            return _continue_consumed_partial_checker(args)
        if args.command == "resume-consumed-partial":
            return _resume_consumed_partial_checker(args)
        if args.command == "refine-consumed-partial":
            return _refine_consumed_partial_checker(args)
        if args.command == "consume-existing-partial":
            return _consume_existing_partial_checker(args)
        if args.command == "checker-escalate-d1":
            return _checker_escalate_d1(args)
        if args.command == "checker-manage-incomplete":
            return _checker_manage_incomplete(args)
        if args.command == "checker-complete-d1":
            return _checker_complete_d1(args)
        if args.command == "inspect-overwatcher-cadence":
            return _inspect_overwatcher_cadence(args)
        if args.command == "inspect-native-activity":
            return _inspect_native_activity(args)
        if args.command == "attest-desktop-overwatcher":
            return _attest_desktop_overwatcher(args)
        if args.command == "notify-supervisor":
            return _notify_supervisor(args)
        if args.command == "continue-worker":
            return _continue_worker(args)
        if args.command == "preflight-run":
            return _preflight_run(args)
        if args.command == "preflight-admission":
            return _preflight_admission(args)
        if args.command == "seal-normal-chain-source":
            return _seal_normal_chain_source(args)
        if args.command == "preflight-new-run":
            return _preflight_new_run(args)
        if args.command == "preflight-conformance-sample":
            return _preflight_conformance_sample(args)
        if args.command == "resume-role-host":
            return _resume_role_host(args)
        if args.command == "reclassify-completed-checker":
            return _reclassify_completed_checker(args)
        if args.command == "continue-staged-handoff":
            return _continue_staged_handoff(args)
        if args.command == "submit-supervisor-decision":
            return _submit_supervisor_decision(args)
        if args.command == "consume-desktop-readback":
            return _consume_desktop_readback(args)
        if args.command == "supervisor-admin":
            return _supervisor_admin(args)
        if args.command == "overwatcher-admin":
            return _overwatcher_admin(args)
        if args.command == "reload-temporal-worker":
            return _reload_temporal_worker(args)
        if args.command == "prepare-runtime-binding-migration":
            return _prepare_runtime_binding_migration(args)
        if args.command == "migrate-runtime-binding":
            return _migrate_runtime_binding(args)
        if args.command == "abandon-pre-start-rejection":
            return _abandon_pre_start_rejection(args)
        if args.command == "prepare-role-credential":
            return _prepare_role_credential(args)
        if args.command == "prepare-incomplete-handoff":
            _emit(prepare_incomplete_worker_handoff(args.source_attempt,
                staged_envelope_path=args.staged_envelope, d0_request_path=args.d0_request))
            return 0
        if args.command == "validate-role-eval":
            return _validate_role_eval(args)
        return _rejected("CLI_COMMAND_INVALID", "unsupported command")
    except AdapterError as exc:
        return _rejected(exc.error_code, str(exc))
    except ContractError as exc:
        return _rejected("CONTRACT_INVALID", str(exc))
    except DrillVerificationError as exc:
        return _rejected("DRILL_EVIDENCE_INVALID", str(exc))
    except CompletionError as exc:
        return _rejected(exc.error_code, str(exc))
    except CheckerEscalationError as exc:
        return _rejected(exc.error_code, str(exc))
    except CheckerCompletionError as exc:
        return _rejected(exc.error_code, str(exc))
    except OverwatcherContinuityError as exc:
        return _rejected("OVERWATCHER_CADENCE_PROJECTION_INVALID", str(exc))
    except NativeActivityError as exc:
        return _rejected("NATIVE_ACTIVITY_INVALID", str(exc))
    except (OSError, ValueError) as exc:
        return _rejected("INPUT_INVALID", str(exc))


if __name__ == "__main__":
    raise SystemExit(main())
