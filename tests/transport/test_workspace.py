from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from slk_transport.workspace import WorkspaceError, preflight_git_workspace


def git(*args: str, cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def test_standalone_git_workspace_and_common_dir_are_writable(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    git("init", cwd=repository)

    result = preflight_git_workspace(repository)

    assert result.worktree_root == repository.resolve()
    assert result.git_common_dir.is_dir()
    assert not list(repository.glob(".slk-write-probe-*"))


def test_linked_worktree_is_rejected_when_common_dir_is_outside_worker_sandbox(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    linked = tmp_path / "linked"
    source.mkdir()
    git("init", cwd=source)
    git("config", "user.email", "test@example.invalid", cwd=source)
    git("config", "user.name", "SLK Test", cwd=source)
    (source / "README.md").write_text("test\n", encoding="utf-8")
    git("add", "README.md", cwd=source)
    git("commit", "-m", "init", cwd=source)
    git("worktree", "add", str(linked), "-b", "linked-test", cwd=source)

    with pytest.raises(WorkspaceError, match="common directory.*outside"):
        preflight_git_workspace(linked)


def test_non_git_workspace_fails_before_execution(tmp_path: Path) -> None:
    with pytest.raises(WorkspaceError, match="Git"):
        preflight_git_workspace(tmp_path)
