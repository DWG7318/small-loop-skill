from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from slk_transport.process import windows_no_window_kwargs


ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.skipif(os.name != "nt", reason="Windows process flags are platform-defined")
def test_windows_no_window_policy_is_explicit_and_headless() -> None:
    kwargs = windows_no_window_kwargs(is_windows=True)

    assert int(kwargs["creationflags"]) & subprocess.CREATE_NO_WINDOW
    startupinfo = kwargs["startupinfo"]
    assert startupinfo.dwFlags & subprocess.STARTF_USESHOWWINDOW
    assert startupinfo.wShowWindow == subprocess.SW_HIDE
    assert windows_no_window_kwargs(is_windows=False) == {}


@pytest.mark.skipif(os.name != "nt", reason="Windows process flags are platform-defined")
def test_detached_policy_keeps_no_window_and_process_group() -> None:
    kwargs = windows_no_window_kwargs(is_windows=True, detached=True)

    flags = int(kwargs["creationflags"])
    assert flags & subprocess.CREATE_NO_WINDOW
    assert flags & subprocess.CREATE_NEW_PROCESS_GROUP
    assert flags & subprocess.DETACHED_PROCESS
    assert flags & subprocess.CREATE_BREAKAWAY_FROM_JOB


def test_every_transport_process_launch_uses_the_shared_policy() -> None:
    required = {
        "src/slk_transport/cli.py": "windows_no_window_kwargs(detached=True)",
        "src/slk_transport/jsonrpc.py": "windows_no_window_kwargs()",
        "src/slk_transport/adapters/dsh.py": "windows_no_window_kwargs()",
        "src/slk_transport/adapters/ocrv.py": "_checker_process_kwargs()",
        "scripts/run_transport_drill.py": "windows_no_window_kwargs()",
    }
    for relative, marker in required.items():
        source = (ROOT / relative).read_text(encoding="utf-8")
        assert marker in source, f"{relative} does not apply the shared headless policy"


def test_native_platform_branch_matches_host_without_opening_a_window() -> None:
    kwargs = windows_no_window_kwargs()
    assert bool(kwargs) is (os.name == "nt")
