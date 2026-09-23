"""One Windows no-window policy for every SLK child process."""

from __future__ import annotations

import os
import subprocess
from typing import Any


def windows_no_window_kwargs(
    *, is_windows: bool | None = None, detached: bool = False
) -> dict[str, Any]:
    """Return subprocess kwargs that never create a visible Windows console."""

    windows = os.name == "nt" if is_windows is None else is_windows
    if not windows:
        return {}
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startupinfo.wShowWindow = subprocess.SW_HIDE
    flags = subprocess.CREATE_NO_WINDOW
    if detached:
        flags |= (
            subprocess.CREATE_NEW_PROCESS_GROUP
            | subprocess.DETACHED_PROCESS
            | subprocess.CREATE_BREAKAWAY_FROM_JOB
        )
    return {"creationflags": flags, "startupinfo": startupinfo}
