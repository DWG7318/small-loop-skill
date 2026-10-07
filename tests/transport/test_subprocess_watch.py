from __future__ import annotations

import subprocess

import pytest

import slk_transport.subprocess_watch as watch


class TimedOutProcess:
    pid = 4242
    args = ["fake-wrapper.cmd"]

    def __init__(self) -> None:
        self.calls = 0

    def communicate(self, timeout=None):
        self.calls += 1
        if self.calls == 1:
            raise subprocess.TimeoutExpired(self.args, timeout)
        return ("", "")


class CompletedProcess:
    returncode = 0

    def __init__(self) -> None:
        self.timeouts: list[float | None] = []

    def communicate(self, timeout=None):
        self.timeouts.append(timeout)
        return ("done", "")


def test_unbounded_finish_waits_without_an_artificial_deadline() -> None:
    process = CompletedProcess()

    result = watch.finish(process, None)  # type: ignore[arg-type]

    assert process.timeouts == [None]
    assert result.returncode == 0
    assert result.stdout == "done"


def test_windows_timeout_terminates_the_entire_process_tree(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    process = TimedOutProcess()
    commands: list[list[str]] = []
    monkeypatch.setattr(watch.os, "name", "nt")
    monkeypatch.setattr(
        watch.subprocess,
        "run",
        lambda command, **_kwargs: commands.append(command),
    )

    with pytest.raises(subprocess.TimeoutExpired):
        watch.finish(process, 0.05)  # type: ignore[arg-type]

    assert commands == [["taskkill", "/PID", "4242", "/T", "/F"]]
