"""Real Windows locks around full installs of explicitly simulated inventories."""
from __future__ import annotations

from contextlib import contextmanager
import ctypes
from ctypes import wintypes
import hashlib
import json
import marshal
import os
from pathlib import Path
import py_compile
import shutil
import sys
from types import CodeType

import pytest

from test_local_install import (
    _encoding_package, run_delivered_verifier, run_installer, seed_old_install,
)
from scripts.verify_local_install import VerificationError, verify


pytestmark = pytest.mark.skipif(os.name != "nt", reason="real Windows sharing locks")
TEMPORAL = Path("tools/slk/runtime/temporal")
PYTHON = Path("tools/slk/runtime/python")
SOURCE = Path("Lib/site-packages/example.py")
CACHE_TAG = sys.implementation.cache_tag


@contextmanager
def locked_runtime(root: Path, executable: str = "temporal.exe"):
    """Allow verification reads, deny deletion/rename of both root and executable."""
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                  wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    handles = []
    try:
        for path, access, flags in ((root, 0x80, 0x02000000), (root / executable, 0x80000000, 0)):
            handle = kernel.CreateFileW(str(path), access, 3, None, 3, flags, None)
            if handle == wintypes.HANDLE(-1).value:
                raise ctypes.WinError(ctypes.get_last_error())
            handles.append(handle)
        # Witness the actual denied directory rename before testing the installer.
        with pytest.raises(OSError) as denied:
            root.rename(root.with_name(root.name + "-lock-witness"))
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


def prepared_with_source(tmp_path: Path, runtime: Path = PYTHON):
    package = _encoding_package(tmp_path)
    source = package / runtime / SOURCE
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(b'"""Verified source fixture."""\nassert True\nvalue = 1\n'
                       b'def compute(arg):\n    captured = arg + value\n'
                       b'    def nested():\n        return captured\n    return nested\n')
    manifest_path = package / "install-manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    manifest["files"].append({"path": source.relative_to(package).as_posix(),
        "size": source.stat().st_size, "sha256": hashlib.sha256(source.read_bytes()).hexdigest()})
    manifest["files"].sort(key=lambda entry: entry["path"])
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    home = tmp_path / "isolated-codex-home"
    previous = seed_old_install(home)
    active = home / runtime
    shutil.copytree(package / runtime, active, dirs_exist_ok=True)
    return package, home, active, previous


def generated_cache(root: Path, name: str = f"example.{CACHE_TAG}.pyc") -> Path:
    cache = root / SOURCE.parent / "__pycache__" / name
    cache.parent.mkdir(parents=True, exist_ok=True)
    optimize = 1 if ".opt-1." in name else 2 if ".opt-2." in name else 0
    py_compile.compile(str(root / SOURCE), cfile=str(cache), doraise=True, optimize=optimize)
    return cache


@pytest.mark.parametrize("cache_name", (f"example.{CACHE_TAG}.pyc", f"example.{CACHE_TAG}.opt-1.pyc",
                                       f"example.{CACHE_TAG}.opt-2.pyc"))
def test_source_backed_python_cache_keeps_locked_runtime_untouched(tmp_path, cache_name):
    package, home, active, _ = prepared_with_source(tmp_path)
    cache = generated_cache(active, cache_name)
    paths = (active, active / "python.exe", active / SOURCE, cache)
    before = {path: identity(path) for path in paths}
    cache_bytes = cache.read_bytes()
    with locked_runtime(active, "python.exe"):
        result = run_installer(package, home)
        assert result.returncode == 0, result.stdout + result.stderr
        receipt = json.loads(result.stdout)
        assert not (Path(receipt["backup_root"]) / PYTHON).exists()
        assert {path: identity(path) for path in paths} == before
        assert cache.read_bytes() == cache_bytes
        assert run_delivered_verifier(home).returncode == 0


@pytest.mark.parametrize("damage", ("changed-source", "unknown-extra", "source-less-bytecode",
                                    "foreign-cache-tag", "non-python-root", "cache-junction"))
def test_cache_exception_does_not_skip_other_runtime_changes(tmp_path, damage):
    runtime = TEMPORAL if damage == "non-python-root" else PYTHON
    package, home, active, _ = prepared_with_source(tmp_path, runtime)
    name = {"source-less-bytecode": f"missing.{CACHE_TAG}.pyc",
            "foreign-cache-tag": "example.pypy314.pyc"}.get(damage, f"example.{CACHE_TAG}.pyc")
    cache = generated_cache(active, name)
    cache_bytes = cache.read_bytes()
    if damage == "changed-source":
        (active / SOURCE).write_bytes(b"value = 2\n")
    elif damage == "unknown-extra":
        (cache.parent / "unexpected.txt").write_bytes(b"not generated bytecode\n")
    elif damage == "cache-junction":
        import _winapi
        outside = tmp_path / "isolated-cache-junction-target"
        cache.parent.rename(outside)
        _winapi.CreateJunction(str(outside), str(cache.parent))
    before = identity(active)
    result = run_installer(package, home)
    assert result.returncode == 0, result.stdout + result.stderr
    backup = Path(json.loads(result.stdout)["backup_root"]) / runtime
    assert identity(active) != before
    assert not cache.exists()
    assert (backup / cache.relative_to(active)).read_bytes() == cache_bytes
    assert (active / SOURCE).read_bytes() == (package / runtime / SOURCE).read_bytes()
    assert run_delivered_verifier(home).returncode == 0


def test_cache_skip_preserves_exact_rollback_snapshot(tmp_path):
    package, home, active, previous = prepared_with_source(tmp_path)
    cache = generated_cache(active)
    before = {path: (identity(path), path.read_bytes()) for path in (active / "python.exe", cache)}
    with locked_runtime(active, "python.exe"):
        result = run_installer(package, home, corrupt="tools/slk/bin/slk-state.exe")
        assert result.returncode != 0
        report = failure_report(home)
        assert "managed file hash mismatch: tools/slk/bin/slk-state.exe" in report["error"]
        assert report["status"] == "ROLLED_BACK" and report["active_tree_verified"] is True
        assert not (Path(report["backup_root"]) / PYTHON).exists()
        assert {path: (identity(path), path.read_bytes()) for path in before} == before
    assert all((home / name).read_bytes() == data for name, data in previous.items()
               if name != (PYTHON / "python.exe").as_posix())


@pytest.mark.parametrize("case", ("allowed", "optimized", "optimized-2", "package-mode", "changed-source", "missing-source",
                                  "source-less-bytecode", "foreign-cache-tag", "unknown-extra", "non-python-root",
                                  "cache-junction", "declared-cache-corrupt", "forged-cache", "malformed-cache",
                                  "alternate-marshal", "wrong-magic", "wrong-flags", "non-code", "trailing-data",
                                  "truncated-payload"))
def test_verifier_python_cache_exception_is_installed_and_manifest_backed_only(tmp_path, case):
    runtime = TEMPORAL if case == "non-python-root" else PYTHON
    package, _, _, _ = prepared_with_source(tmp_path, runtime)
    if case != "package-mode":
        shutil.copy2(package / "install-manifest.json", package / "tools/slk/install-manifest.json")
    name = {"optimized": f"example.{CACHE_TAG}.opt-1.pyc", "optimized-2": f"example.{CACHE_TAG}.opt-2.pyc",
            "source-less-bytecode": f"missing.{CACHE_TAG}.pyc",
            "foreign-cache-tag": "example.pypy314.pyc"}.get(case, f"example.{CACHE_TAG}.pyc")
    cache = generated_cache(package / runtime, name)
    if case == "changed-source":
        (package / runtime / SOURCE).write_bytes(b"value = 2\n")
    elif case == "missing-source":
        (package / runtime / SOURCE).unlink()
    elif case == "unknown-extra":
        (cache.parent / "unexpected.txt").write_bytes(b"unknown extra\n")
    elif case == "forged-cache":
        # Preserve a real timestamp/size header while substituting different code.
        wrong = compile(b"value = 999\n", str(package / runtime / SOURCE), "exec", dont_inherit=True)
        cache.write_bytes(cache.read_bytes()[:16] + marshal.dumps(wrong))
    elif case == "malformed-cache":
        cache.write_bytes(b"not a CPython cache\n")
    elif case == "alternate-marshal":
        code = compile((package / runtime / SOURCE).read_bytes(), str(package / runtime / SOURCE),
                       "exec", dont_inherit=True)
        alternate = marshal.dumps(code, 2)
        assert alternate != marshal.dumps(code)
        cache.write_bytes(cache.read_bytes()[:16] + alternate)
    elif case == "wrong-magic":
        cache.write_bytes(b"BAD!" + cache.read_bytes()[4:])
    elif case == "wrong-flags":
        cache.write_bytes(cache.read_bytes()[:4] + (2).to_bytes(4, "little") + cache.read_bytes()[8:])
    elif case == "non-code":
        cache.write_bytes(cache.read_bytes()[:16] + marshal.dumps("not a code object"))
    elif case == "trailing-data":
        cache.write_bytes(cache.read_bytes() + b"unexpected trailing data")
    elif case == "truncated-payload":
        cache.write_bytes(cache.read_bytes()[:17])
    elif case == "cache-junction":
        import _winapi
        outside = tmp_path / "isolated-cache-junction-target"
        cache.parent.rename(outside)
        _winapi.CreateJunction(str(outside), str(cache.parent))
    elif case == "declared-cache-corrupt":
        manifest_path = package / "tools/slk/install-manifest.json"
        manifest = json.loads(manifest_path.read_bytes())
        manifest["files"].append({"path": cache.relative_to(package).as_posix(), "size": cache.stat().st_size,
            "sha256": hashlib.sha256(cache.read_bytes()).hexdigest()})
        manifest["files"].sort(key=lambda entry: entry["path"])
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        cache.write_bytes(b"corrupted declared cache\n")
    if case in {"allowed", "optimized", "optimized-2", "alternate-marshal"}:
        assert verify(package)["status"] == "PASS"
    else:
        with pytest.raises(VerificationError):
            verify(package, package_mode=case == "package-mode")


@pytest.mark.parametrize("nested", (False, True))
@pytest.mark.parametrize("field", ("co_stacksize", "co_varnames", "co_freevars", "co_cellvars",
                                   "co_qualname", "co_exceptiontable"))
def test_verifier_rejects_changed_code_execution_layout(tmp_path, nested, field):
    package, _, _, _ = prepared_with_source(tmp_path)
    shutil.copy2(package / "install-manifest.json", package / "tools/slk/install-manifest.json")
    source = package / PYTHON / SOURCE
    cache = generated_cache(package / PYTHON)
    code = compile(source.read_bytes(), str(source), "exec", dont_inherit=True)
    target = next(item for item in code.co_consts if isinstance(item, CodeType)) if nested else code
    original = getattr(target, field)
    changed = original + 1 if field == "co_stacksize" else (
        original + "_changed" if field == "co_qualname" else (
            original + b"\x00" if field == "co_exceptiontable" else original + ("unexpected_layout_slot",)))
    updates = {field: changed}
    if field == "co_varnames":
        updates["co_nlocals"] = len(changed)
    altered = target.replace(**updates)
    if nested:
        altered = code.replace(co_consts=tuple(altered if item is target else item for item in code.co_consts))
    cache.write_bytes(cache.read_bytes()[:16] + marshal.dumps(altered))
    with pytest.raises(VerificationError):
        verify(package)


@pytest.mark.parametrize("damage", ("forged-cache", "malformed-cache"))
def test_untrusted_cache_never_installs_and_locked_runtime_is_restored_exactly(tmp_path, damage):
    package, home, active, previous = prepared_with_source(tmp_path)
    cache = generated_cache(active)
    if damage == "forged-cache":
        wrong = compile(b"value = 999\n", str(active / SOURCE), "exec", dont_inherit=True)
        cache.write_bytes(cache.read_bytes()[:16] + marshal.dumps(wrong))
    else:
        cache.write_bytes(b"not a CPython cache\n")
    before = {path: identity(path) for path in (active, active / "python.exe", cache)}
    cache_bytes = cache.read_bytes()
    with locked_runtime(active, "python.exe"):
        result = run_installer(package, home)
        assert result.returncode != 0
        assert '"status":"INSTALLED"' not in result.stdout
        report = failure_report(home)
        assert "installed managed surface has missing or extra files: tools/slk/runtime/python" in report["error"]
        assert report["status"] == "ROLLED_BACK" and report["active_tree_verified"] is True
        assert {path: identity(path) for path in before} == before
        assert cache.read_bytes() == cache_bytes
    assert all((home / name).read_bytes() == data for name, data in previous.items()
               if name != (PYTHON / "python.exe").as_posix())
