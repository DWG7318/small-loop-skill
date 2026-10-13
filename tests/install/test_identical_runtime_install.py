"""Real Windows locks around full installs of explicitly simulated inventories."""
from __future__ import annotations

from contextlib import contextmanager
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import shutil

import pytest

from test_local_install import (
    _encoding_package, run_delivered_verifier, run_installer, seed_old_install,
)


pytestmark = pytest.mark.skipif(os.name != "nt", reason="real Windows sharing locks")
TEMPORAL = Path("tools/slk/runtime/temporal")


@contextmanager
def locked_runtime(root: Path):
    """Allow verification reads, deny deletion/rename of both root and executable."""
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                  wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    handles = []
    try:
        for path, access, flags in ((root, 0x80, 0x02000000), (root / "temporal.exe", 0x80000000, 0)):
            handle = kernel.CreateFileW(str(path), access, 3, None, 3, flags, None)
            if handle == wintypes.HANDLE(-1).value:
                raise ctypes.WinError(ctypes.get_last_error())
            handles.append(handle)
        # Witness the actual denied directory rename before testing the installer.
        with pytest.raises(OSError) as denied:
            root.rename(root.with_name("temporal-lock-witness"))
        assert denied.value.winerror in {5, 32}, denied.value
        assert root.is_dir()
        yield
    finally:
        for handle in reversed(handles):
            kernel.CloseHandle(handle)


def prepared(tmp_path: Path):
    # No release binaries or repository MANIFEST mutation: this is a closed,
    # verified fixture package using the real installer and isolated Node setup.
    package = _encoding_package(tmp_path)
    home = tmp_path / "isolated-codex-home"
    previous = seed_old_install(home)
    active = home / TEMPORAL
    shutil.copytree(package / TEMPORAL, active)
    return package, home, active, previous


def identity(path: Path):
    value = path.stat()
    return value.st_dev, value.st_ino, value.st_mtime_ns


def failure_report(home: Path):
    reports = list((home / ".tmp").glob("slk-install-failed-*.json"))
    assert len(reports) == 1
    return json.loads(reports[0].read_text(encoding="utf-8-sig"))


def test_identical_locked_runtime_is_not_moved_or_replaced(tmp_path):
    package, home, active, previous = prepared(tmp_path)
    before = {path: identity(path) for path in (active, active / "temporal.exe", active / "LICENSE")}
    with locked_runtime(active):
        result = run_installer(package, home)
        assert result.returncode == 0, result.stdout + result.stderr
        receipt = json.loads(result.stdout)
        assert not (Path(receipt["backup_root"]) / TEMPORAL).exists()
        assert {path: identity(path) for path in before} == before
        assert run_delivered_verifier(home).returncode == 0
    # Other managed roots still use the ordinary replacement/backup transaction.
    old_bin = "tools/slk/bin/slk-state.exe"
    assert (home / old_bin).read_bytes() == (package / old_bin).read_bytes()
    assert (Path(receipt["backup_root"]) / old_bin).read_bytes() == previous[old_bin]


@pytest.mark.parametrize("damage", ["changed", "missing", "extra", "hidden-extra"])
def test_nonidentical_runtime_is_replaced_as_a_complete_root(tmp_path, damage):
    package, home, active, _ = prepared(tmp_path)
    if damage == "changed":
        (active / "LICENSE").write_bytes(b"different original fixture bytes")
    elif damage == "missing":
        (active / "LICENSE").unlink()
    else:
        extra = active / "unlisted.txt"
        extra.write_bytes(b"extra fixture file must not survive")
        if damage == "hidden-extra":
            assert ctypes.windll.kernel32.SetFileAttributesW(str(extra), 2)
    before = identity(active)
    result = run_installer(package, home)
    assert result.returncode == 0, result.stdout + result.stderr
    receipt = json.loads(result.stdout)
    assert identity(active) != before
    assert (Path(receipt["backup_root"]) / TEMPORAL).is_dir()
    assert {p.name: p.read_bytes() for p in active.iterdir()} == {
        p.name: p.read_bytes() for p in (package / TEMPORAL).iterdir()}
    assert run_delivered_verifier(home).returncode == 0


def test_same_bytes_through_a_junction_are_not_retained_as_a_managed_runtime(tmp_path):
    import _winapi

    package, home, active, _ = prepared(tmp_path)
    outside = tmp_path / "isolated-junction-target"
    active.rename(outside)
    _winapi.CreateJunction(str(outside), str(active))
    old = {p.name: p.read_bytes() for p in outside.iterdir()}
    result = run_installer(package, home)
    assert result.returncode == 0, result.stdout + result.stderr
    assert not active.is_junction()
    receipt = json.loads(result.stdout)
    assert (Path(receipt["backup_root"]) / TEMPORAL).is_junction()
    assert {p.name: p.read_bytes() for p in outside.iterdir()} == old
    assert run_delivered_verifier(home).returncode == 0


def test_changed_locked_runtime_fails_safely_without_preserving_wrong_bytes_as_installed(tmp_path):
    package, home, active, previous = prepared(tmp_path)
    (active / "LICENSE").write_bytes(b"different original fixture bytes")
    before = {path: identity(path) for path in (active, active / "temporal.exe", active / "LICENSE")}
    with locked_runtime(active):
        result = run_installer(package, home)
        assert result.returncode != 0
        report = failure_report(home)
        assert report["status"] == "ROLLED_BACK" and report["active_tree_verified"] is True
        assert {path: identity(path) for path in before} == before
    assert (active / "LICENSE").read_bytes() == b"different original fixture bytes"
    assert all((home / name).read_bytes() == data for name, data in previous.items())


def test_final_verification_failure_rolls_back_other_roots_without_touching_retained_runtime(tmp_path):
    package, home, active, previous = prepared(tmp_path)
    before = {path: identity(path) for path in (active, active / "temporal.exe", active / "LICENSE")}
    with locked_runtime(active):
        result = run_installer(package, home, corrupt="tools/slk/bin/slk-state.exe")
        assert result.returncode != 0
        report = failure_report(home)
        assert "managed file hash mismatch: tools/slk/bin/slk-state.exe" in report["error"]
        assert report["status"] == "ROLLED_BACK" and report["active_tree_verified"] is True
        assert {path: identity(path) for path in before} == before
        assert not (Path(report["backup_root"]) / TEMPORAL).exists()
    assert all((home / name).read_bytes() == data for name, data in previous.items())
