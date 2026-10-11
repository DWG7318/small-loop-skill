"""Explicit scratch-home configuration; never use the real native user home."""
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def helper():
    spec = importlib.util.spec_from_file_location("configure_ocrv", ROOT / "scripts/configure_ocrv.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def roots(tmp_path):
    slk = tmp_path / "selected tools/slk"
    user = tmp_path / "native 中文 %literal% ^home"
    backup = tmp_path / "existing-install-backup"
    for relative in ("runtime/python/python.exe", "runtime/ocrv/slk_checker_decision.py", "bin/slk-transport.pyz"):
        path = slk / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"fixture inventory")
    target = user / ".opencodereview/config.json"
    target.parent.mkdir(parents=True)
    return slk, user, backup, target


def test_merge_preserves_nonowned_tree_and_is_idempotent(tmp_path):
    module = helper()
    slk, user, backup, target = roots(tmp_path)
    original = {"telemetry": False, "empty": [], "provider": {"private": "fixture"},
                "mcp_servers": {"other": {"args": [], "enabled": False},
                    "slk_checker_decision": {"future": [], "enabled": False, "command": "old"}}}
    data = json.dumps(original).encode()
    target.write_bytes(data)
    state = module.configure(slk, user, backup)
    expected = json.loads(data)
    expected["mcp_servers"]["slk_checker_decision"].update({
        "type": "stdio", "command": str(slk / "runtime/python/python.exe"),
        "args": ["-B", str(slk / "runtime/ocrv/slk_checker_decision.py"), "--transport", str(slk / "bin/slk-transport.pyz")],
        "tools": ["slk_checker_decide", "slk_read_evidence"]})
    assert json.loads(target.read_bytes()) == expected
    assert (backup / "ocrv-config.original.json").read_bytes() == data
    before = (target.read_bytes(), target.stat().st_mtime_ns)
    assert module.configure(slk, user, tmp_path / "must-not-be-created")["changed"] is False
    assert not (tmp_path / "must-not-be-created").exists()
    assert (target.read_bytes(), target.stat().st_mtime_ns) == before
    assert module.rollback(user, backup, state) is True
    assert target.read_bytes() == data


@pytest.mark.parametrize("data", (b"not JSON", b"[]", b'{"mcp_servers":false}', b'{"mcp_servers":{"slk_checker_decision":[]}}'))
def test_bad_config_is_untouched(tmp_path, data):
    module = helper()
    slk, user, backup, target = roots(tmp_path)
    target.write_bytes(data)
    with pytest.raises((ValueError, json.JSONDecodeError)):
        module.configure(slk, user, backup)
    assert target.read_bytes() == data
    assert not backup.exists()


def test_atomic_failure_keeps_original(tmp_path, monkeypatch):
    module = helper()
    slk, user, backup, target = roots(tmp_path)
    original = b'{"telemetry": false, "keep": []}\n'
    target.write_bytes(original)
    monkeypatch.setattr(module.os, "replace", lambda *_: (_ for _ in ()).throw(OSError("fixture atomic failure")))
    with pytest.raises(OSError, match="atomic failure"):
        module.configure(slk, user, backup)
    assert target.read_bytes() == original
    assert (backup / "ocrv-config.original.json").read_bytes() == original
    assert list(target.parent.iterdir()) == [target]


@pytest.mark.parametrize("external_edit", (False, True))
def test_new_config_rollback_does_not_clobber_external_edits(tmp_path, external_edit):
    module = helper()
    slk, user, backup, target = roots(tmp_path)
    state = module.configure(slk, user, backup)
    if external_edit:
        target.write_bytes(b'{"external":true}')
    assert module.rollback(user, backup, state) is (not external_edit)
    if external_edit:
        assert target.read_bytes() == b'{"external":true}'
    else:
        assert not target.exists()


def test_existing_config_rollback_does_not_clobber_external_edits(tmp_path):
    module = helper()
    slk, user, backup, target = roots(tmp_path)
    target.write_bytes(b'{"telemetry":false}')
    state = module.configure(slk, user, backup)
    target.write_bytes(b'{"external":[]}')
    assert module.rollback(user, backup, state) is False
    assert target.read_bytes() == b'{"external":[]}'
