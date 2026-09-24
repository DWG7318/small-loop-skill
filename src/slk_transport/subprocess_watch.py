"""Bounded foreground subprocess helpers with no detached runtime."""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from .process import windows_no_window_kwargs


@dataclass(frozen=True)
class ProcessResult:
    returncode: int
    stdout: str
    stderr: str


def spawn(command: Sequence[str], *, cwd: str, env: Mapping[str, str], process_kwargs: Mapping[str, Any]) -> subprocess.Popen[str]:
    return subprocess.Popen(
        list(command), cwd=cwd, env=dict(env), text=True, encoding="utf-8", errors="replace",
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, **dict(process_kwargs),
    )


def finish(process: subprocess.Popen[str], timeout_seconds: float) -> ProcessResult:
    try:
        stdout, stderr = process.communicate(timeout=max(timeout_seconds, 0.001))
    except subprocess.TimeoutExpired:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
                **windows_no_window_kwargs(),
            )
        else:
            process.kill()
        stdout, stderr = process.communicate(timeout=5)
        raise subprocess.TimeoutExpired(process.args, timeout_seconds, output=stdout, stderr=stderr)
    return ProcessResult(process.returncode, stdout or "", stderr or "")
