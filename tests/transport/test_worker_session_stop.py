"""Read-only stop proof uses the real native durable parser, never its cache."""

import importlib
import importlib.util
import json
from pathlib import Path
import subprocess

import pytest

from test_worker_completion import completion_fixture


BUNDLE = Path("C:/Users/DWG/.codex/tools/slk")
NODE = BUNDLE / "runtime/node/node.exe"
PARSER = BUNDLE / "runtime/dsh/node_modules/@deepseek-ai/dsh-session-persistence-jsonl/lib/index.js"
SESSION = "session-11111111-1111-4111-8111-111111111111"


def test_native_stop_helper_is_available():
    assert importlib.util.find_spec("slk_transport.worker_session_stop") is not None, "native stop helper is missing"


@pytest.fixture
def stop():
    assert importlib.util.find_spec("slk_transport.worker_session_stop") is not None, "native stop helper is missing"
    return importlib.import_module("slk_transport.worker_session_stop").native_session_stopped


@pytest.fixture
def native_fixture(tmp_path):
    if not NODE.is_file() or not PARSER.is_file():
        pytest.skip("bundled native Session parser is unavailable")
    _source, endpoint, _checker = completion_fixture(tmp_path)
    endpoint["address"]["command"] = [str(BUNDLE / "bin/dsh-slk.cmd")]
    root = tmp_path / "runtime/runs/RUN-A-worker/home/sessions"
    log = root / "--project--" / SESSION / "session.v4.jsonl.zstd"
    log.parent.mkdir(parents=True)
    header = {"type": "session", "version": 4, "id": SESSION, "createdAt": 1700000000000,
              "cwd": endpoint["address"]["cwd"], "isSeeded": False, "delegationDepth": 0}
    events = [
        {"seq": 0, "time": 1700000000001, "type": "turn/start", "data": {"turn": 1}},
        {"seq": 1, "time": 1700000000002, "type": "turn/end", "data": {"turn": 1, "reason": {"kind": "completed"}}},
    ]

    def save(rows=None, meta=None, target=log):
        # Native storage appends independently checksummed frames; a whole-file
        # zstdDecompressSync would incorrectly inspect only the header frame.
        script = "const z=require('node:zlib'),f=require('node:fs'); const r=JSON.parse(f.readFileSync(0,'utf8')); process.stdout.write(Buffer.concat(r.map(x=>z.zstdCompressSync(Buffer.from(JSON.stringify(x)+'\\n'),{params:{[z.constants.ZSTD_c_checksumFlag]:1}}))));"
        result = subprocess.run([str(NODE), "-e", script], input=json.dumps([meta or header, *(events if rows is None else rows)]).encode(),
                                capture_output=True, check=True, timeout=15)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(result.stdout)
        return target

    save()
    return endpoint, log, header, events, save


def test_closed_durable_turn_produces_small_proof_without_changing_files(stop, native_fixture):
    endpoint, log, _header, _events, _save = native_fixture
    before = log.read_bytes()
    # A different Session is deliberately unreadable and must not be scanned.
    unrelated = log.parent.parent / "session-other" / "session.v4.jsonl.zstd"
    unrelated.parent.mkdir()
    unrelated.write_bytes(b"not a native log")
    proof = stop(endpoint)
    assert proof["status"] == "NATIVE_SESSION_STOPPED"
    assert proof["session_id"] == SESSION
    assert Path(proof["path"]) == log.resolve()
    assert proof["last_seq"] == 1 and proof["turn"] == 1
    assert len(proof["sha256"]) == 64
    assert log.read_bytes() == before
    assert set(log.parent.iterdir()) == {log}


def test_open_native_turn_rejects_even_when_projection_cache_says_closed(stop, native_fixture):
    endpoint, log, _header, events, save = native_fixture
    save(rows=events[:1])
    cache = log.parents[2].parent / "storages/session_projcache/sessions" / (SESSION + ".json")
    cache.parent.mkdir(parents=True)
    cache.write_text(json.dumps({"version": 7, "record": {"rows": {"turnBoundary": {
        "ver": 2, "seq": 1, "val": {"openTurnStartSeq": None}}}}}), encoding="utf-8")
    with pytest.raises(ValueError):
        stop(endpoint)


@pytest.mark.parametrize("damage", ["wrong-session", "wrong-cwd", "duplicate", "torn", "corrupt", "legacy", "empty"])
def test_unproved_or_ambiguous_native_session_rejects(stop, native_fixture, damage):
    endpoint, log, header, events, save = native_fixture
    if damage == "wrong-session": save(meta={**header, "id": "session-other"})
    if damage == "wrong-cwd": save(meta={**header, "cwd": str(log.parent)})
    if damage == "duplicate": save(target=log.parents[2] / "--another-project--" / SESSION / log.name)
    if damage == "torn": log.write_bytes(log.read_bytes() + b"\x28\xb5\x2f")
    if damage == "corrupt": log.write_bytes(b"not a native log")
    if damage == "legacy": log.rename(log.with_name("session.v3.jsonl.zstd"))
    if damage == "empty": save(rows=[])
    with pytest.raises(ValueError):
        stop(endpoint)


def test_unsupported_legacy_launcher_rejects_before_node(stop, native_fixture, monkeypatch):
    endpoint, _log, _header, _events, _save = native_fixture
    endpoint["address"]["command"] = ["D:/DSH/dsh-slk.cmd"]
    monkeypatch.setattr(subprocess, "run", lambda *_args, **_kw: pytest.fail("unsupported launcher executed a helper"))
    with pytest.raises(ValueError, match="bundled"):
        stop(endpoint)
