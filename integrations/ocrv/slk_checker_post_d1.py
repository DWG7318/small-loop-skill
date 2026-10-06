#!/usr/bin/env python3
"""Headless OCRV entry for the authenticated SLK Checker post-D1 suffix."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


FAIL_REQUEST_SCHEMA = "slk.checker-post-d1-request/v1"
PASS_REQUEST_SCHEMA = "slk.checker-completion-request/v1"


def windows_no_window_kwargs() -> dict[str, object]:
    if os.name != "nt":
        return {}
    startup = subprocess.STARTUPINFO()
    startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startup.wShowWindow = subprocess.SW_HIDE
    return {
        "creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0),
        "startupinfo": startup,
    }


def _read_request(path: Path, schema: str) -> tuple[dict[str, Any], bytes]:
    data = path.read_bytes()
    value = json.loads(data.decode("utf-8-sig"))
    if not isinstance(value, dict) or value.get("schema_version") != schema:
        raise ValueError("request schema is invalid")
    command = value.get("transport_command")
    if not isinstance(command, list) or not command or not all(
        isinstance(item, str) and item and item == item.strip() for item in command
    ):
        raise ValueError("transport command is invalid")
    return value, data


def _expected_output(request: dict[str, Any], *, pass_route: bool, completing: bool) -> Path:
    root_field = "handoff_attempt_root" if pass_route else "escalation_attempt_root"
    invocation_field = "completion_invocation_id" if pass_route else "post_d1_invocation_id"
    root = Path(str(request.get(root_field, ""))).resolve()
    invocation = request.get(invocation_field)
    if not isinstance(invocation, str) or not invocation or invocation != invocation.strip():
        raise ValueError("post-D1 invocation identity is invalid")
    name = (
        "committed-result.json"
        if completing
        else "result.json"
        if pass_route
        else "prepared-result.json"
    )
    directory = ".checker-completion" if pass_route else ".checker-post-d1"
    return (root / directory / invocation / name).resolve()


def _write_atomic(path: Path, value: dict[str, Any]) -> None:
    encoded = (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
    if path.is_file():
        if path.read_bytes() != encoded:
            raise ValueError("immutable post-D1 result conflicts")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def main() -> int:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--slk-post-d1", action="store_true")
    mode.add_argument("--slk-complete-d1", action="store_true")
    parser.add_argument("--request", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--host-receipt", type=Path)
    args = parser.parse_args()
    try:
        pass_route = bool(args.slk_complete_d1)
        schema = PASS_REQUEST_SCHEMA if pass_route else FAIL_REQUEST_SCHEMA
        request, data = _read_request(args.request.resolve(), schema)
        expected = _expected_output(
            request,
            pass_route=pass_route,
            completing=args.host_receipt is not None,
        )
        if args.output.resolve() != expected:
            raise ValueError("output path does not match the immutable suffix phase")
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        print(f"SLK_OCRV_POST_D1_INVALID: {exc}", file=sys.stderr)
        return 4

    arguments = [
        *request["transport_command"],
        "checker-complete-d1" if pass_route else "checker-escalate-d1",
        "--request",
        str(args.request.resolve()),
        "--sha256",
        hashlib.sha256(data).hexdigest(),
    ]
    if args.host_receipt is not None:
        arguments.extend(["--host-receipt", str(args.host_receipt.resolve())])
    environment = os.environ.copy()
    environment.pop("SLK_ROLE_CREDENTIAL", None)
    environment.pop("SLK_OVERWATCHER_CREDENTIAL", None)
    try:
        completed = subprocess.run(
            arguments,
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
        print(f"SLK_OCRV_POST_D1_HOST_FAILED: {exc}", file=sys.stderr)
        return 5
    if completed.returncode != 0:
        if completed.stdout:
            sys.stdout.write(completed.stdout)
        if completed.stderr:
            sys.stderr.write(completed.stderr)
        return completed.returncode
    try:
        result = json.loads(completed.stdout)
        accepted_statuses = (
            {"CHECKER_COMPLETION_COMMITTED", "DESKTOP_BRIDGE_REQUIRED"}
            if pass_route
            else {"DESKTOP_BRIDGE_REQUIRED", "CHECKER_ESCALATION_COMMITTED"}
        )
        if not isinstance(result, dict) or result.get("status") not in accepted_statuses:
            raise ValueError("managed transport returned an invalid post-D1 result")
        _write_atomic(expected, result)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"SLK_OCRV_POST_D1_RESULT_INVALID: {exc}", file=sys.stderr)
        return 5
    sys.stdout.write(completed.stdout)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
