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
from .checker_completion import CheckerCompletionError, execute_checker_completion
from .desktop_current_turn import (
    complete_desktop_current_turn,
    prepare_desktop_current_turn,
)
from .contracts import ContractError, Endpoint, Envelope, parse_delivery
from .dispatcher import dispatch_once
from .drill_verify import DrillVerificationError, verify_drill
from .evidence import Attempt
from .native_activity import NativeActivityError, collect_overwatch_scope, inspect_native_activity, validate_native_start
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
from .overwatcher_continuity import OverwatcherContinuityError, inspect_overwatcher_cadence
from .worker_completion import CompletionError, inspect_worker_completion


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
    output_delivery = None
    if host is not None:
        source = args.attempt_root / result.run_id / result.message_id
        try:
            output_delivery = host.complete(source)
        except (ValueError, OSError) as exc:
            # Engineering completion is immutable and is not handoff success.
            from .worker_completion import _write_or_reuse_stable_request
            root = source / "role-host"
            root.mkdir(parents=True, exist_ok=True)
            failure = {"status": "HOST_HANDOFF_FAILED", "run_id": result.run_id,
                       "source_message_id": result.message_id,
                       "error_code": getattr(exc, "error_code", type(exc).__name__)}
            _write_or_reuse_stable_request(root / f"failure-{failure['error_code']}.json", failure)
            output_delivery = {**failure, "message": str(exc)}
    native_result = result.to_dict()
    if host is None:
        _emit(native_result)
        return 0 if result.status == "completed" else 3
    delivery_failed = output_delivery.get("status") in {
        "OUTPUT_DELIVERY_UNCONFIRMED", "HOST_HANDOFF_FAILED",
    } or output_delivery.get("handoff", {}).get("status") == "failed"
    _emit({"status": "failed" if delivery_failed else result.status,
           "run_id": result.run_id, "message_id": result.message_id,
           "native_result": native_result, "output_delivery": output_delivery})
    return 5 if delivery_failed else 0 if result.status == "completed" else 3


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
            _emit({**value, "job_pid": process.pid, "ack_scope": "NATIVE_RECEIVE_START_ONLY"})
            return 3
        if completed.is_file():
            value = _read_object(completed, "completed result")
            _emit({**value, "job_pid": process.pid, "ack_scope": "NATIVE_RECEIVE_START_ONLY"})
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
                    "ack_scope": "NATIVE_RECEIVE_START_ONLY",
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
            "ack_scope": "NATIVE_RECEIVE_START_ONLY",
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
        encoded = (json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
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


def _inspect_overwatcher_cadence(args: argparse.Namespace) -> int:
    result = inspect_overwatcher_cadence(
        _read_object(args.runtime_projection, "runtime projection"),
        observed_at=args.observed_at,
    )
    _emit(result)
    return 3 if result["status"] in {"LATE", "CONTINUITY_UNPROVEN"} else 0


def _inspect_native_activity(args: argparse.Namespace) -> int:
    if getattr(args, "run_id", None) is not None or getattr(args, "state_command", None) is not None:
        if not args.run_id or not args.state_command:
            raise ValueError("scope query requires both the exact Run and state command")
        if args.desktop_overwatcher_attestation is not None:
            raise ValueError("engineering scope query cannot substitute an OW attestation")
        result = collect_overwatch_scope(args.started, run_id=args.run_id, state_command=args.state_command)
        _emit(result)
        return 0 if result["native_activity"]["error"] is None else 3
    terminals = tuple(path for path in (args.completed, args.failed) if path is not None)
    if args.started is None:
        raise ValueError("native activity query requires its original started.json")
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


def _preflight_recovery_endpoints(host: RoleHost) -> None:
    from .run_readiness import _tool_exists
    for role in ("supervisor", "checker", "worker"):
        endpoint = Endpoint.from_dict(host.endpoint(role))
        ADAPTERS[endpoint.adapter].validate_address(endpoint)
        command = endpoint.address.get("command", [])
        if "desktop" in endpoint.address:
            from .adapters.codex_desktop import validate_desktop_address
            command = validate_desktop_address(endpoint.address)
        if command and not _tool_exists(command[0]):
            raise ValueError(f"registered {role} executable is unavailable")


def _inspect_recovery_authority(args: argparse.Namespace) -> int:
    path = args.binding.resolve()
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != args.sha256:
        raise ValueError("role host binding hash changed")
    host = RoleHost(_read_object(path, "role host binding"), digest)
    _preflight_recovery_endpoints(host)
    _emit(host.inspect_recovery_authority(args.supervisor_role_instance_id))
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


def _submit_worker_action(args: argparse.Namespace) -> int:
    import os
    native = Path(os.environ.get("SLK_NATIVE_ACTIVITY_PATH", ""))
    if not native.is_absolute() or native.name != "native-activity.json":
        raise CompletionError("WORKER_ACTION_CALLER_UNPROVEN", "no bound Worker invocation")
    source = native.parent
    host = load_role_host(_read_object(source / "endpoint.json", "Worker endpoint"))
    if host is None:
        raise CompletionError("ROLE_HOST_BINDING_INVALID", "prepared Worker binding is missing")
    details = _read_object(args.details, "Worker action details") if args.details else {}
    _emit(host.record_worker_action(source, args.event, details))
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
    native_activity.add_argument("--started", type=Path)
    native_activity.add_argument("--completed", type=Path)
    native_activity.add_argument("--failed", type=Path)
    native_activity.add_argument("--run-id", help="collect current central and native scope in one real tool-clock window")
    native_activity.add_argument("--state-command", nargs="+", help="exact current state/query command for --run-id")
    native_activity.add_argument("--desktop-overwatcher-attestation", type=Path)
    native_activity.add_argument("--desktop-overwatcher-attestation-sha256")
    ow_desktop = subparsers.add_parser("attest-desktop-overwatcher")
    ow_desktop.add_argument("--request", required=True, type=Path)
    ow_desktop.add_argument("--sha256", required=True)
    ow_desktop.add_argument("--evidence-root", required=True, type=Path)
    notice = subparsers.add_parser("notify-supervisor")
    notice.add_argument("--request", required=True, type=Path)
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
    recovery_authority = subparsers.add_parser("inspect-recovery-authority")
    recovery_authority.add_argument("--binding", required=True, type=Path)
    recovery_authority.add_argument("--sha256", required=True)
    recovery_authority.add_argument("--supervisor-role-instance-id", required=True)
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
    worker_submit = subparsers.add_parser("submit-worker-action")
    worker_submit.add_argument("--event", required=True, choices=["WORK_STARTED", "D0_COMPLETED", "CANDIDATE_SUBMITTED"])
    worker_submit.add_argument("--details", type=Path)
    desktop_readback = subparsers.add_parser("consume-desktop-readback")
    desktop_readback.add_argument("--source-attempt", required=True, type=Path)
    supervisor_admin = subparsers.add_parser("supervisor-admin")
    supervisor_admin.add_argument("--request", required=True, type=Path)
    supervisor_admin.add_argument("--sha256", required=True)
    d2_start = subparsers.add_parser("start-d2", help="start D2 through the sealed Supervisor admin request")
    d2_start.add_argument("--request", required=True, type=Path)
    d2_start.add_argument("--sha256", required=True)
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
        if args.command == "inspect-recovery-authority":
            return _inspect_recovery_authority(args)
        if args.command == "continue-staged-handoff":
            return _continue_staged_handoff(args)
        if args.command == "submit-supervisor-decision":
            return _submit_supervisor_decision(args)
        if args.command == "submit-worker-action":
            return _submit_worker_action(args)
        if args.command == "consume-desktop-readback":
            return _consume_desktop_readback(args)
        if args.command == "supervisor-admin":
            return _supervisor_admin(args)
        if args.command == "start-d2":
            if _read_object(args.request, "D2 admin request").get("operation") != "start-d2":
                raise ValueError("start-d2 requires the exact sealed start-d2 action")
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
