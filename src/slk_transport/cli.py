"""Command-line entry point for the SLK transport artifact."""

from __future__ import annotations

import argparse
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
from .desktop_current_turn import (
    complete_desktop_current_turn,
    prepare_desktop_current_turn,
)
from .contracts import ContractError, Endpoint, Envelope, parse_delivery
from .dispatcher import dispatch_once
from .drill_verify import DrillVerificationError, verify_drill
from .native_activity import NativeActivityError, inspect_native_activity, validate_native_start
from .process import windows_no_window_kwargs
from .recovery import inspect_delivery, retry_exact
from .role_eval import load_pack, pack_sha256, validate_response
from .run_readiness import evaluate_run_readiness
from .overwatcher_continuity import OverwatcherContinuityError, inspect_overwatcher_cadence
from .worker_completion import (
    CompletionError,
    consume_staged_checker_terminal,
    continuation_request_bytes,
    execute_checker_recovery,
    execute_worker_continuation,
    inspect_worker_completion,
    prepare_invalid_result_recovery_envelope,
    recover_staged_checker_commit,
)


VERSION = "4.3.6"
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
    result = dispatch_once(
        endpoint_raw,
        envelope_raw,
        args.attempt_root,
        adapters=ADAPTERS,
    )
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


def _inspect_overwatcher_cadence(args: argparse.Namespace) -> int:
    result = inspect_overwatcher_cadence(
        _read_object(args.runtime_projection, "runtime projection"),
        observed_at=args.observed_at,
    )
    _emit(result)
    return 3 if result["status"] in {"LATE", "CONTINUITY_UNPROVEN"} else 0


def _inspect_native_activity(args: argparse.Namespace) -> int:
    terminals = tuple(path for path in (args.completed, args.failed) if path is not None)
    result = inspect_native_activity(args.started, terminal_paths=terminals)
    _emit(result)
    return 0 if result["status"] in {"ACTIVE", "IDLE", "PENDING", "COMPLETED", "FAILED"} else 3


def _preflight_run(args: argparse.Namespace) -> int:
    result = evaluate_run_readiness(_read_object(args.request, "Run readiness request"))
    _emit(result)
    return 0 if result["status"] == "READY" else 3


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
    commit_recovery = subparsers.add_parser("recover-staged-checker-commit")
    commit_recovery.add_argument("--continuation", required=True, type=Path)
    commit_recovery.add_argument("--outcome", required=True, type=Path)
    commit_recovery.add_argument("--failed-request", required=True, type=Path)
    terminal_consumer = subparsers.add_parser("consume-staged-checker-terminal")
    terminal_consumer.add_argument("--request", required=True, type=Path)
    terminal_consumer.add_argument("--sha256", required=True)
    checker_escalation = subparsers.add_parser("checker-escalate-d1")
    checker_escalation.add_argument("--request", required=True, type=Path)
    checker_escalation.add_argument("--sha256", required=True)
    checker_escalation.add_argument("--host-receipt", type=Path)
    cadence = subparsers.add_parser("inspect-overwatcher-cadence")
    cadence.add_argument("--runtime-projection", required=True, type=Path)
    cadence.add_argument("--observed-at", required=True)
    native_activity = subparsers.add_parser("inspect-native-activity")
    native_activity.add_argument("--started", required=True, type=Path)
    native_activity.add_argument("--completed", type=Path)
    native_activity.add_argument("--failed", type=Path)
    continuation = subparsers.add_parser("continue-worker")
    continuation.add_argument("--request", required=True, type=Path)
    continuation.add_argument("--sha256", required=True)
    readiness = subparsers.add_parser("preflight-run")
    readiness.add_argument("--request", required=True, type=Path)
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
        if args.command == "checker-recover-worker":
            return _checker_recover_worker(args)
        if args.command == "prepare-invalid-result-recovery":
            return _prepare_invalid_result_recovery(args)
        if args.command == "recover-staged-checker-commit":
            return _recover_staged_checker_commit(args)
        if args.command == "consume-staged-checker-terminal":
            return _consume_staged_checker_terminal(args)
        if args.command == "checker-escalate-d1":
            return _checker_escalate_d1(args)
        if args.command == "inspect-overwatcher-cadence":
            return _inspect_overwatcher_cadence(args)
        if args.command == "inspect-native-activity":
            return _inspect_native_activity(args)
        if args.command == "continue-worker":
            return _continue_worker(args)
        if args.command == "preflight-run":
            return _preflight_run(args)
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
    except OverwatcherContinuityError as exc:
        return _rejected("OVERWATCHER_CADENCE_PROJECTION_INVALID", str(exc))
    except NativeActivityError as exc:
        return _rejected("NATIVE_ACTIVITY_INVALID", str(exc))
    except (OSError, ValueError) as exc:
        return _rejected("INPUT_INVALID", str(exc))


if __name__ == "__main__":
    raise SystemExit(main())
