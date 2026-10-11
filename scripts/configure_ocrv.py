"""Merge only SLK's MCP fields in an explicitly selected native OCRV home."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".slk-config-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def _target(user_home: Path) -> Path:
    if not user_home.is_absolute():
        raise ValueError("native OCRV user home must be explicit and absolute")
    return user_home / ".opencodereview/config.json"


def configure(slk_root: Path, user_home: Path, backup_root: Path) -> dict:
    if not slk_root.is_absolute() or not backup_root.is_absolute():
        raise ValueError("SLK and existing installation backup roots must be absolute")
    target = _target(user_home)
    original = target.read_bytes() if target.exists() else None
    value = json.loads(original.decode("utf-8-sig")) if original is not None else {}
    if not isinstance(value, dict):
        raise ValueError("native OCRV config must be a JSON object")
    servers = value.setdefault("mcp_servers", {})
    if not isinstance(servers, dict):
        raise ValueError("mcp_servers must be a JSON object")
    entry = servers.setdefault("slk_checker_decision", {})
    if not isinstance(entry, dict):
        raise ValueError("slk_checker_decision must be a JSON object")
    python = slk_root / "runtime/python/python.exe"
    decision = slk_root / "runtime/ocrv/slk_checker_decision.py"
    transport = slk_root / "bin/slk-transport.pyz"
    if not all(path.is_file() for path in (python, decision, transport)):
        raise ValueError("selected installed SLK MCP runtime is incomplete")
    owned = {"type": "stdio", "command": str(python),
             "args": ["-B", str(decision), "--transport", str(transport)],
             "tools": ["slk_checker_decide", "slk_read_evidence"]}
    if all(entry.get(key) == item for key, item in owned.items()):
        return {"changed": False}
    entry.update(owned)
    data = (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")
    backup_root.mkdir(parents=True, exist_ok=True)
    if original is not None:
        # The installer supplies a unique existing transaction backup directory.
        # Exclusive creation must never replace a previous original.
        with (backup_root / "ocrv-config.original.json").open("xb") as stream:
            stream.write(original)
    if (target.read_bytes() if target.exists() else None) != original:
        raise ValueError("native OCRV config changed during installation")
    _atomic(target, data)
    return {"changed": True, "original_existed": original is not None,
            "original_sha256": _digest(original) if original is not None else "",
            "installed_sha256": _digest(data)}


def rollback(user_home: Path, backup_root: Path, state: dict) -> bool:
    if not state.get("changed"):
        return True
    target = _target(user_home)
    if not target.is_file() or _digest(target.read_bytes()) != state["installed_sha256"]:
        return False  # An external edit/deletion belongs to its author.
    if state["original_existed"]:
        original = (backup_root / "ocrv-config.original.json").read_bytes()
        if _digest(original) != state["original_sha256"]:
            raise ValueError("native OCRV configuration backup hash mismatch")
        _atomic(target, original)
    else:
        target.unlink()
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--slk-root", required=True, type=Path)
    parser.add_argument("--ocrv-user-home", required=True, type=Path)
    parser.add_argument("--backup-root", required=True, type=Path)
    parser.add_argument("--rollback-state", help="non-sensitive state returned by this installation transaction")
    args = parser.parse_args()
    try:
        if args.rollback_state is not None:
            restored = rollback(args.ocrv_user_home, args.backup_root, json.loads(args.rollback_state))
            print(json.dumps({"restored": restored}))
            return 0 if restored else 2
        print(json.dumps(configure(args.slk_root, args.ocrv_user_home, args.backup_root)))
        return 0
    except (OSError, ValueError):
        # Do not echo native config contents, accounts, tokens or provider values.
        print("OCRV configuration setup/restore failed; inspect the selected installation backup", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
