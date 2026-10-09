"""Long content stays complete while the native Desktop read fits its real API."""
from dataclasses import asdict
import hashlib
import json

import pytest

from slk_transport.adapters.base import AdapterError
from slk_transport.adapters.codex import CodexAdapter
from slk_transport.adapters.codex_desktop import MATERIAL_PREFIX, consume_desktop_readback, deliver_desktop, validate_late_desktop_start
from slk_transport.contracts import Envelope, canonical_json_sha256
from slk_transport.dispatcher import dispatch_once
from slk_transport.evidence import AttemptStore
from slk_transport.recovery import retry_exact
from test_codex_desktop import prepared
from test_codex_adapter import supervisor_envelope


@pytest.mark.parametrize("body", ["x" * 20516, "真实证据<&>" * 5000], ids=["original-size", "xml-expanded"])
def test_large_desktop_material_is_complete_hash_bound_and_fits_native_read(tmp_path, monkeypatch, body):
    endpoint = prepared(tmp_path, monkeypatch)
    envelope = supervisor_envelope()
    attempt = AttemptStore(tmp_path / "attempts").create(envelope)
    assert deliver_desktop(endpoint, envelope, attempt, body).status == "completed"
    material = attempt.root / "desktop-material.json"
    value = json.loads(material.read_text(encoding="utf-8"))
    assert value["prompt"] == body and value["envelope"] == asdict(envelope)
    sent = json.loads((attempt.root / "desktop-prompt.json").read_text())["prompt"]
    reference = json.loads(sent[len(MATERIAL_PREFIX):])
    assert reference["path"] == str(material.resolve())
    assert reference["bytes"] == material.stat().st_size
    assert reference["sha256"] == hashlib.sha256(material.read_bytes()).hexdigest()
    calls = [json.loads(line) for line in (tmp_path / "native-calls.jsonl").read_text().splitlines()]
    reads = [c["arguments"] for c in calls if c["name"] == "read_thread"]
    assert reads[0]["includeOutputs"] is False and reads[0]["maxOutputCharsPerItem"] == 4096
    assert all(r["maxOutputCharsPerItem"] <= 20000 for r in reads)
    assert all(r["includeOutputs"] is True for r in reads[1:])
    assert sum(c["name"] == "send_message_to_thread" for c in calls) == 1


@pytest.mark.parametrize("damage", ["missing", "changed", "wrong-envelope"])
def test_large_material_drift_blocks_late_native_proof_without_resend(tmp_path, monkeypatch, damage):
    endpoint = prepared(tmp_path, monkeypatch, "unconfirmed")
    envelope = supervisor_envelope()
    attempt = AttemptStore(tmp_path / "attempts").create(envelope)
    with pytest.raises(AdapterError, match="accepted send lacks"):
        deliver_desktop(endpoint, envelope, attempt, "x" * 20516)
    material = attempt.root / "desktop-material.json"
    if damage == "missing":
        material.unlink()
    else:
        value = json.loads(material.read_text())
        if damage == "changed": value["prompt"] += "changed"
        else: value["envelope"]["message_id"] = "wrong-message"
        material.write_text(json.dumps(value), encoding="utf-8")
    before = (tmp_path / "native-calls.jsonl").read_bytes()
    monkeypatch.setenv("FAKE_DESKTOP_MODE", "late-confirmed")
    with pytest.raises(AdapterError) as rejected:
        consume_desktop_readback(endpoint, envelope, attempt)
    assert rejected.value.error_code == "CODEX_DESKTOP_READBACK_DRIFT"
    assert (tmp_path / "native-calls.jsonl").read_bytes() == before
    assert not (attempt.root / "started.json").exists()


def test_large_material_late_readback_keeps_original_failure_and_never_resends(tmp_path, monkeypatch):
    endpoint = prepared(tmp_path, monkeypatch, "unconfirmed")
    original = supervisor_envelope()
    payload = {**original.payload, "summary": "x" * 20516}
    envelope = Envelope.from_dict({**asdict(original), "payload": payload,
                                  "payload_sha256": canonical_json_sha256(payload)})
    result = dispatch_once(asdict(endpoint), asdict(envelope), tmp_path / "attempts", adapters={endpoint.adapter: CodexAdapter()})
    assert result.error_code == "CODEX_DESKTOP_READBACK_UNPROVED"
    attempt = AttemptStore(tmp_path / "attempts").create(envelope)
    original_failure = (attempt.root / "failed.json").read_bytes()
    monkeypatch.setenv("FAKE_DESKTOP_MODE", "late-confirmed")
    assert consume_desktop_readback(endpoint, envelope, attempt).status == "completed"
    assert validate_late_desktop_start(endpoint, envelope, attempt).status == "completed"
    assert (attempt.root / "failed.json").read_bytes() == original_failure


def test_pre_send_tool_failure_exact_retry_preserves_original_envelope_and_failure(tmp_path, monkeypatch):
    endpoint = prepared(tmp_path, monkeypatch)
    original = supervisor_envelope()
    payload = {**original.payload, "summary": "x" * 20516}
    envelope = Envelope.from_dict({**asdict(original), "payload": payload,
                                  "payload_sha256": canonical_json_sha256(payload)})
    root = tmp_path / "attempts"
    attempt = AttemptStore(root).create(envelope)
    attempt.write_json_once("endpoint.json", asdict(endpoint))
    attempt.write_json_once("envelope.json", asdict(envelope))
    attempt.write_json_once("accepted.json", {"message_id": envelope.message_id, "run_id": envelope.run_id, "status": "accepted"})
    attempt.write_json_once("failed.json", {"schema_version": "slk.transport-result/v1", "message_id": envelope.message_id,
        "run_id": envelope.run_id, "adapter": endpoint.adapter, "status": "failed", "native_identity": {},
        "error_code": "CODEX_DESKTOP_TOOL_FAILED", "evidence": ["accepted.json", "endpoint.json", "envelope.json"]})
    hashes = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in attempt.root.iterdir()}
    result = retry_exact(root, asdict(endpoint), asdict(envelope), adapters={endpoint.adapter: CodexAdapter()})
    assert result["status"] == "RETRY_COMPLETED"
    assert all(hashlib.sha256((attempt.root / name).read_bytes()).hexdigest() == digest for name, digest in hashes.items())


def test_metadata_only_read_retains_old_active_turn_output_id_and_cannot_prove_new_start(tmp_path, monkeypatch):
    endpoint = prepared(tmp_path, monkeypatch, "active-old-output")
    envelope = supervisor_envelope()
    attempt = AttemptStore(tmp_path / "attempts").create(envelope)
    prompt = CodexAdapter()._prompt(envelope, attempt)
    monkeypatch.setenv("FAKE_DESKTOP_OLD_PROMPT", prompt)
    with pytest.raises(AdapterError) as rejected:
        deliver_desktop(endpoint, envelope, attempt, prompt)
    assert rejected.value.error_code == "CODEX_DESKTOP_READBACK_UNPROVED"
    anchor = json.loads((attempt.root / "desktop-readback-anchor.json").read_text())
    assert "item-exact" in anchor["previous_item_ids"]
    assert not (attempt.root / "started.json").exists()
