#!/usr/bin/env python3
"""Narrow OCRV launcher for one authenticated SLK Worker-completion recovery."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path


def windows_no_window_kwargs() -> dict[str, object]:
    if os.name != "nt":
        return {}
    startup = subprocess.STARTUPINFO()
    startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startup.wShowWindow = subprocess.SW_HIDE
    return {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0), "startupinfo": startup}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--slk-worker-recovery", action="store_true", required=True)
    parser.add_argument("--request", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        data = args.request.read_bytes()
        request = json.loads(data.decode("utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        print(f"SLK_OCRV_RECOVERY_INVALID: {exc}", file=sys.stderr)
        return 4
    if (
        not isinstance(request, dict)
        or request.get("schema_version") != "slk.ocrv-worker-recovery-request/v1"
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
    completed = subprocess.run(
        command
        + [
            "checker-recover-worker",
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
    if completed.stdout:
        sys.stdout.write(completed.stdout)
    if completed.stderr:
        sys.stderr.write(completed.stderr)
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
