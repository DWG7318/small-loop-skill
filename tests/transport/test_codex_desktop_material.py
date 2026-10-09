"""Both Codex entries send immutable material references, never task-body excerpts."""
from dataclasses import asdict, replace
import hashlib
import json

import pytest

from slk_transport.adapters.base import AdapterError
from slk_transport.adapters.codex import CodexAdapter
from slk_transport.adapters.codex_desktop import MATERIAL_PREFIX, _prepare_prompt, consume_desktop_readback, deliver_desktop, validate_late_desktop_start
from slk_transport.contracts import ContractError, Envelope, canonical_json_sha256
from slk_transport.dispatcher import dispatch_once
from slk_transport.evidence import AttemptStore
from slk_transport.recovery import retry_exact
from test_codex_desktop import prepared
from test_codex_adapter import codex_endpoint, supervisor_envelope


@pytest.mark.parametrize("runtime", ["desktop", "app-server"])
def test_native_material_instruction_requires_identity_checks_and_exact_failure_report(tmp_path, monkeypatch, runtime):
    endpoint = prepared(tmp_path, monkeypatch) if runtime == "desktop" else codex_endpoint(tmp_path)
    endpoint = replace(endpoint, address={**endpoint.address, "startup_timeout_seconds": 5})
    envelope = supervisor_envelope()
    attempt = AttemptStore(tmp_path / "attempts").create(envelope)

    assert CodexAdapter().deliver(endpoint, envelope, attempt).status == "completed"

    if runtime == "desktop":
        calls = [json.loads(line) for line in (tmp_path / "native-calls.jsonl").read_text().splitlines()]
        sent = next(call["arguments"]["prompt"] for call in calls if call["name"] == "send_message_to_thread")
    else:
        lines = (attempt.root / "native.stdout.txt").read_text(encoding="utf-8").splitlines()
        requests = [json.loads(line[2:]) for line in lines if line.startswith("C ")]
        sent = next(item["params"]["input"][0]["text"] for item in requests if item.get("method") == "turn/start")
    instruction = sent.split("\n", 1)[0]
    for field in ("run_id", "cell_id", "message_id", "payload_sha256"):
        assert field in instruction
    assert "assigned role/Session" in instruction
    assert "byte count" in instruction and "SHA-256" in instruction
    assert "missing material or any mismatch, stop and report the exact original location and cause" in instruction
    assert "do not guess content or use a fallback endpoint" in instruction
    assert "Supervisor decision/result/submit instructions" in instruction


@pytest.mark.parametrize("damage", ["unchanged", "missing", "changed"])
def test_historical_material_prefix_remains_hash_bound_without_rewriting(tmp_path, damage):
    legacy_prefix = (
        "SLK cross-Agent delivery. Read the complete UTF-8 JSON material at the absolute path below; "
        "verify its byte count and SHA-256 before work. Its envelope is the unchanged assigned work; "
        "follow its full prompt, including any Supervisor decision/result/submit instructions. "
        "Do not truncate evidence, treat this as status-only, or locate another task by title.\n"
    )
    envelope = supervisor_envelope()
    attempt = AttemptStore(tmp_path / "attempts").create(envelope)
    current = _prepare_prompt("complete original task", envelope, attempt)
    historical = legacy_prefix + current[len(MATERIAL_PREFIX):]
    material = attempt.root / "desktop-material.json"
    original_bytes = material.read_bytes()
    if damage == "unchanged":
        assert _prepare_prompt(historical, envelope, attempt) == historical
        assert material.read_bytes() == original_bytes
    else:
        if damage == "missing":
            material.unlink()
        else:
            material.write_bytes(original_bytes + b"\n")
        with pytest.raises(AdapterError) as rejected:
            _prepare_prompt(historical, envelope, attempt)
        assert rejected.value.error_code == "CODEX_DESKTOP_READBACK_DRIFT"
        assert str(material.resolve()) in str(rejected.value)


def test_short_desktop_task_uses_the_same_complete_material_reference(tmp_path, monkeypatch):
    monkeypatch.setenv("PYTHONUTF8", "1")  # Python native fixtures speak the UTF-8 production protocol.
    workspace = tmp_path / "中文 工作区"
    workspace.mkdir()
    endpoint = prepared(workspace, monkeypatch)
    envelope = supervisor_envelope()
    attempt = AttemptStore(workspace / "交接 材料").create(envelope)
    body = "Read original evidence, make the Supervisor decision, then submit it. 完整任务。"

    assert deliver_desktop(endpoint, envelope, attempt, body).status == "completed"

    sent = json.loads((attempt.root / "desktop-prompt.json").read_text(encoding="utf-8"))["prompt"]
    assert sent.startswith(MATERIAL_PREFIX)
    reference = json.loads(sent[len(MATERIAL_PREFIX):])
    material = attempt.root / "desktop-material.json"
    data = material.read_bytes()
    assert reference == {
        "path": str(material.resolve()), "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(), "message_id": envelope.message_id,
        "run_id": envelope.run_id, "cell_id": envelope.cell_id,
        "payload_sha256": envelope.payload_sha256,
    }
    assert json.loads(data) == {
        "schema_version": "slk.desktop-material/v1", "envelope": asdict(envelope), "prompt": body,
    }


@pytest.mark.parametrize("summary", ["完整短任务", "真实证据<&>" * 5000], ids=["short", "long"])
def test_app_server_sends_the_same_reference_and_preserves_supervisor_actions(tmp_path, monkeypatch, summary):
    monkeypatch.setenv("PYTHONUTF8", "1")
    workspace = tmp_path / "中文 工作区"
    workspace.mkdir()
    endpoint = codex_endpoint(workspace)
    original = supervisor_envelope()
    payload = {
        "d1_event_id": "D1-pass", "required_cell_ids": [original.cell_id],
        "accepted_cell_ids": [original.cell_id], "final_candidate_message_id": original.message_id,
        "d2_criteria": [summary], "evidence_refs": ["Git 外 原件"],
    }
    envelope = Envelope.from_dict({**asdict(original), "payload_type": "D2_READY",
        "payload": payload, "payload_sha256": canonical_json_sha256(payload)})
    monkeypatch.setenv("SLK_TRANSPORT_ROLE_HOST", str(workspace / "unavailable-private-binding.json"))
    attempt = AttemptStore(workspace / "交接 材料").create(envelope)
    adapter = CodexAdapter()
    full_prompt = adapter._prompt(envelope, attempt)

    assert adapter.deliver(endpoint, envelope, attempt).status == "completed"

    material = attempt.root / "desktop-material.json"
    assert material.is_file()
    transcript = (attempt.root / "native.stdout.txt").read_text(encoding="utf-8").splitlines()
    requests = [json.loads(line[2:]) for line in transcript if line.startswith("C ")]
    start = next(item["params"] for item in requests if item.get("method") == "turn/start")
    sent = start["input"][0]["text"]
    assert sent.startswith(MATERIAL_PREFIX)
    reference = json.loads(sent[len(MATERIAL_PREFIX):])
    data = material.read_bytes()
    assert reference == {
        "path": str(material.resolve()), "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(), "message_id": envelope.message_id,
        "run_id": envelope.run_id, "cell_id": envelope.cell_id,
        "payload_sha256": envelope.payload_sha256,
    }
    value = json.loads(data)
    assert value == {"schema_version": "slk.desktop-material/v1",
        "envelope": asdict(envelope), "prompt": full_prompt}
    assert "slk.supervisor-result/v1" in value["prompt"]
    assert "submit" in value["prompt"] and "explicit" in value["prompt"]
    assert "unavailable-private-binding" not in value["prompt"]
    assert start["clientUserMessageId"] == envelope.message_id
    assert start["threadId"] == endpoint.address["thread_id"]
    started = json.loads((attempt.root / "started.json").read_text(encoding="utf-8"))
    assert started["request_sha256"] == envelope.payload_sha256
    assert started["native_request_sha256"] == hashlib.sha256(sent.encode("utf-8")).hexdigest()


@pytest.mark.parametrize("runtime", ["desktop", "app-server"])
def test_material_reference_operation_replay_preserves_identity_without_native_launch(tmp_path, monkeypatch, runtime):
    endpoint = prepared(tmp_path, monkeypatch) if runtime == "desktop" else codex_endpoint(tmp_path)
    envelope = supervisor_envelope()
    args = (asdict(endpoint), asdict(envelope), tmp_path / "attempts")
    adapter = CodexAdapter()

    first = dispatch_once(*args, adapters={endpoint.adapter: adapter})
    attempt = AttemptStore(tmp_path / "attempts").create(envelope)
    material = attempt.root / "desktop-material.json"
    assert material.is_file()
    originals = {path.name: path.read_bytes() for path in attempt.root.iterdir() if path.is_file()}
    calls = (tmp_path / "native-calls.jsonl").read_bytes() if runtime == "desktop" else None
    monkeypatch.setattr(adapter, "deliver", lambda *_: pytest.fail("same operation must not launch again"))

    assert dispatch_once(*args, adapters={endpoint.adapter: adapter}) == first
    changed = asdict(envelope)
    changed["sender_role_instance_id"] = "different-session"
    with pytest.raises(ContractError, match="identity collision"):
        dispatch_once(asdict(endpoint), changed, tmp_path / "attempts", adapters={endpoint.adapter: adapter})
    assert all((attempt.root / name).read_bytes() == data for name, data in originals.items())
    if calls is not None:
        assert (tmp_path / "native-calls.jsonl").read_bytes() == calls


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


@pytest.mark.parametrize("body", ["short task", "x" * 20516], ids=["short", "long"])
@pytest.mark.parametrize("damage", ["missing", "changed", "wrong-envelope"])
def test_material_drift_blocks_late_native_proof_without_resend(tmp_path, monkeypatch, damage, body):
    endpoint = prepared(tmp_path, monkeypatch, "unconfirmed")
    envelope = supervisor_envelope()
    attempt = AttemptStore(tmp_path / "attempts").create(envelope)
    with pytest.raises(AdapterError, match="accepted send lacks"):
        deliver_desktop(endpoint, envelope, attempt, body)
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
    assert str(material.resolve()) in str(rejected.value)
    assert (tmp_path / "native-calls.jsonl").read_bytes() == before
    assert not (attempt.root / "started.json").exists()


@pytest.mark.parametrize("damage", ["path", "bytes", "sha256", "run_id", "cell_id", "message_id", "payload_sha256"])
def test_material_reference_fields_cannot_redirect_or_rebind_an_existing_task(tmp_path, damage):
    envelope = supervisor_envelope()
    attempt = AttemptStore(tmp_path / "attempts").create(envelope)
    original = _prepare_prompt("x" * 20516, envelope, attempt, "caller-exact")
    reference = json.loads(original[len(MATERIAL_PREFIX):])
    reference[damage] = reference[damage] + 1 if damage == "bytes" else "wrong-identity"
    changed = MATERIAL_PREFIX + json.dumps(reference, ensure_ascii=False, sort_keys=True)
    before = (attempt.root / "desktop-material.json").read_bytes()

    with pytest.raises(AdapterError) as rejected:
        _prepare_prompt(changed, envelope, attempt, "caller-exact")

    assert rejected.value.error_code == "CODEX_DESKTOP_READBACK_DRIFT"
    assert (attempt.root / "desktop-material.json").read_bytes() == before
    assert _prepare_prompt(original, envelope, attempt, "caller-exact") == original


def test_historical_inline_readback_keeps_the_original_receipt_without_material(tmp_path, monkeypatch):
    from slk_transport.adapters import codex_desktop as desktop

    endpoint = prepared(tmp_path, monkeypatch, "unconfirmed")
    envelope = supervisor_envelope()
    attempt = AttemptStore(tmp_path / "attempts").create(envelope)
    prompt = CodexAdapter()._prompt(envelope, attempt)
    # Emulate the old sender only; the saved receipt and current readback validation remain real.
    with monkeypatch.context() as historical:
        historical.setattr(desktop, "_prepare_prompt", lambda text, *_: text)
        result = dispatch_once(asdict(endpoint), asdict(envelope), tmp_path / "attempts",
            adapters={endpoint.adapter: CodexAdapter()})
    assert result.error_code == "CODEX_DESKTOP_READBACK_UNPROVED"
    assert not (attempt.root / "desktop-material.json").exists()
    originals = {name: (attempt.root / name).read_bytes() for name in
        ("failed.json", "desktop-send.json", "desktop-prompt.json", "desktop-readback-anchor.json")}
    monkeypatch.setenv("FAKE_DESKTOP_MODE", "late-confirmed")

    assert consume_desktop_readback(endpoint, envelope, attempt, prompt).status == "completed"
    assert validate_late_desktop_start(endpoint, envelope, attempt).status == "completed"
    assert all((attempt.root / name).read_bytes() == data for name, data in originals.items())
    calls = [json.loads(line) for line in (tmp_path / "native-calls.jsonl").read_text().splitlines()]
    assert sum(call["name"] == "send_message_to_thread" for call in calls) == 1


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
    monkeypatch.setenv("FAKE_DESKTOP_OLD_PROMPT", _prepare_prompt(prompt, envelope, attempt, "caller-exact"))
    with pytest.raises(AdapterError) as rejected:
        deliver_desktop(endpoint, envelope, attempt, prompt)
    assert rejected.value.error_code == "CODEX_DESKTOP_READBACK_UNPROVED"
    anchor = json.loads((attempt.root / "desktop-readback-anchor.json").read_text())
    assert "item-exact" in anchor["previous_item_ids"]
    assert not (attempt.root / "started.json").exists()
