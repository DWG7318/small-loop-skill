"""Command-line entry point for the SLK transport artifact."""

from __future__ import annotations

import argparse
import json
import os
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
from .contracts import ContractError, Endpoint, Envelope, parse_delivery
from .dispatcher import dispatch_once
from .drill_verify import DrillVerificationError, verify_drill


VERSION = "4.0.0"
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
    flags = 0
    start_new_session = False
    if os.name == "nt":
        flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
    else:
        start_new_session = True
    with stdout_path.open("wb") as stdout, stderr_path.open("wb") as stderr:
        process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=stdout,
            stderr=stderr,
            close_fds=True,
            creationflags=flags,
            start_new_session=start_new_session,
        )
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


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="slk-transport")
    parser.add_argument("--version", action="version", version=f"slk-transport {VERSION}")
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name in ("validate", "job", "send"):
        command = subparsers.add_parser(name)
        command.add_argument("--endpoint", required=True, type=Path)
        command.add_argument("--envelope", required=True, type=Path)
        if name in {"job", "send"}:
            command.add_argument("--attempt-root", required=True, type=Path)
        if name == "send":
            command.add_argument("--startup-timeout-seconds", type=float, default=30.0)
    drill_verify = subparsers.add_parser("drill-verify")
    drill_verify.add_argument("--evidence-root", required=True, type=Path)
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
        return _rejected("CLI_COMMAND_INVALID", "unsupported command")
    except AdapterError as exc:
        return _rejected(exc.error_code, str(exc))
    except ContractError as exc:
        return _rejected("CONTRACT_INVALID", str(exc))
    except DrillVerificationError as exc:
        return _rejected("DRILL_EVIDENCE_INVALID", str(exc))
    except (OSError, ValueError) as exc:
        return _rejected("INPUT_INVALID", str(exc))


if __name__ == "__main__":
    raise SystemExit(main())
