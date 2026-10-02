#!/usr/bin/env python3
"""Narrow OCRV launcher for one authenticated SLK Worker-completion recovery."""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path


def windows_no_window_kwargs() -> dict[str, object]:
    if os.name != "nt":
        return {}
    startup = subprocess.STARTUPINFO()
    startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startup.wShowWindow = subprocess.SW_HIDE
    return {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0), "startupinfo": startup}


def _creation_time(pid: int) -> str:
    if os.name != "nt":
        fields = Path(f"/proc/{pid}/stat").read_text(encoding="ascii").split()
        return f"proc-start:{fields[21]}"
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.restype = ctypes.c_void_p
    handle = kernel32.OpenProcess(0x1000, False, pid)
    if not handle:
        raise OSError("recovery process identity unavailable")
    try:
        created = ctypes.c_ulonglong()
        exited = ctypes.c_ulonglong()
        kernel = ctypes.c_ulonglong()
        user = ctypes.c_ulonglong()
        if not kernel32.GetProcessTimes(
            handle, ctypes.byref(created), ctypes.byref(exited), ctypes.byref(kernel), ctypes.byref(user)
        ):
            raise OSError("recovery process creation time unavailable")
        return f"win-filetime:{created.value}"
    finally:
        kernel32.CloseHandle(handle)


def _publish_start(native_request_sha256: str, invocation_id: str) -> None:
    path_raw = os.environ.get("SLK_NATIVE_START_RECEIPT")
    context_raw = os.environ.get("SLK_NATIVE_START_CONTEXT")
    if not path_raw or not context_raw:
        return
    context = json.loads(context_raw)
    if context.get("native_request_sha256") != native_request_sha256:
        raise ValueError("native start request hash mismatch")
    value = {
        "schema_version": "slk.native-start/v2",
        "status": "STARTED",
        "adapter": context["adapter"],
        "run_id": context["run_id"],
        "cell_id": context["cell_id"],
        "message_id": context["message_id"],
        "request_sha256": context["request_sha256"],
        "native_request_sha256": native_request_sha256,
        "observed_at": datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z"),
        "process": {"pid": os.getpid(), "creation_time": _creation_time(os.getpid())},
        "native_task": {
            "kind": "ocrv-recovery-wrapper",
            "id": invocation_id,
            "status": "RUNNING",
        },
    }
    destination = Path(path_raw).resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(value, stream, ensure_ascii=False, sort_keys=True, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def main() -> int:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--slk-worker-recovery", action="store_true")
    mode.add_argument("--slk-existing-terminal", action="store_true")
    mode.add_argument("--slk-committed-terminal", action="store_true")
    parser.add_argument("--request", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        data = args.request.read_bytes()
        request = json.loads(data.decode("utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        print(f"SLK_OCRV_RECOVERY_INVALID: {exc}", file=sys.stderr)
        return 4
    expected_schema = (
        "slk.ocrv-committed-terminal-request/v1"
        if args.slk_committed_terminal
        else "slk.ocrv-worker-recovery-request/v1"
    )
    if (
        not isinstance(request, dict)
        or request.get("schema_version") != expected_schema
        or Path(str(request.get("result_path", ""))).resolve() != args.output.resolve()
    ):
        print("SLK_OCRV_RECOVERY_INVALID: request identity mismatch", file=sys.stderr)
        return 4
    command = request.get("transport_command")
    if not isinstance(command, list) or not command or not all(isinstance(item, str) and item for item in command):
        print("SLK_OCRV_RECOVERY_INVALID: transport command is invalid", file=sys.stderr)
        return 4
    environment = os.environ.copy()
    environment.pop("SLK_ROLE_CREDENTIAL", None)
    environment.pop("SLK_OVERWATCHER_CREDENTIAL", None)
    if args.slk_existing_terminal or args.slk_committed_terminal:
        environment.pop("SLK_NATIVE_START_RECEIPT", None)
        environment.pop("SLK_NATIVE_START_CONTEXT", None)
    if args.slk_worker_recovery:
        try:
            _publish_start(
                hashlib.sha256(data).hexdigest(),
                str(request.get("recovery_invocation_id", "")),
            )
        except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
            print(f"SLK_OCRV_RECOVERY_INVALID: {exc}", file=sys.stderr)
            return 4
    try:
        internal_command = (
            "checker-record-committed-terminal"
            if args.slk_committed_terminal
            else "checker-recover-worker"
        )
        completed = subprocess.run(
            command
            + [
                internal_command,
                "--request",
                str(args.request.resolve()),
                "--sha256",
                hashlib.sha256(data).hexdigest(),
            ],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            env=environment,
            **windows_no_window_kwargs(),
        )
    except OSError as exc:
        print(f"SLK_OCRV_RECOVERY_HOST_FAILED: {exc}", file=sys.stderr)
        return 5
    if completed.stdout:
        sys.stdout.write(completed.stdout)
    if completed.stderr:
        sys.stderr.write(completed.stderr)
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
