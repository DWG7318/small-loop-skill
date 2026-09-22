"""Readiness checks for a real writable Git worktree and common directory."""

from __future__ import annotations

import os
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path

from .process import windows_no_window_kwargs


class WorkspaceError(RuntimeError):
    """Raised when Worker construction would not have a safe Git workspace."""


@dataclass(frozen=True)
class GitWorkspace:
    worktree_root: Path
    git_common_dir: Path


def _git_value(cwd: Path, argument: str) -> str:
    completed = subprocess.run(
        ["git", "rev-parse", argument],
        cwd=cwd,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
        **windows_no_window_kwargs(),
    )
    if completed.returncode != 0 or not completed.stdout.strip():
        raise WorkspaceError(f"Git workspace preflight failed for {argument}")
    return completed.stdout.strip()


def _probe(directory: Path) -> None:
    name = f".slk-write-probe-{uuid.uuid4().hex}"
    path = directory / name
    descriptor: int | None = None
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        os.write(descriptor, b"slk-preflight\n")
        os.fsync(descriptor)
    except OSError as exc:
        raise WorkspaceError(f"Git workspace path is not writable: {directory}") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)
        path.unlink(missing_ok=True)


def preflight_git_workspace(cwd: Path | str) -> GitWorkspace:
    requested = Path(cwd).resolve()
    if not requested.is_dir():
        raise WorkspaceError("Git workspace must be an existing directory")
    root = Path(_git_value(requested, "--show-toplevel")).resolve()
    common_value = Path(_git_value(requested, "--git-common-dir"))
    common = (requested / common_value).resolve() if not common_value.is_absolute() else common_value.resolve()
    if not root.is_dir() or not common.is_dir():
        raise WorkspaceError("Git worktree or common directory does not exist")
    try:
        requested.relative_to(root)
    except ValueError as exc:
        raise WorkspaceError("requested Worker cwd is outside the resolved Git worktree") from exc
    _probe(root)
    if common != root:
        _probe(common)
    return GitWorkspace(root, common)
