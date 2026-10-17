"""Frozen Main originals travel to the existing OCRV indexed reader, not Git."""

import importlib.util
import json
import sys
from pathlib import Path

import pytest

from slk_transport.adapters.ocrv import OcrvAdapter
from slk_transport.adapters.base import AdapterError
from slk_transport.contracts import Envelope
from slk_transport.role_host import RoleHost
from slk_transport import worker_completion as wc
from test_role_host import prepared_host
from test_worker_completion import write_json


def load_ocrv(name):
    path = Path(__file__).parents[2] / "integrations/ocrv" / name
    spec = importlib.util.spec_from_file_location(path.stem + "_frozen_materials", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def material_host(tmp_path, *, with_bytes=True):
    host, source, envelope = prepared_host(tmp_path)
    original = tmp_path / "frozen-main-contract.md"
    original.write_text("冻结主合同原文\n" * 3000 + "最后一行不可省略", encoding="utf-8")
    ref = {"path": str(original), "sha256": wc._sha256(original)}
    if with_bytes:
        ref["bytes"] = original.stat().st_size
    cell = {**host.binding["cells"][0], "evidence_refs": [ref]}
    host = RoleHost({**host.binding, "cells": [cell]}, "b" * 64)
    return host, source, envelope, original, ref


def deliver(host, source, monkeypatch):
    sent = []
    monkeypatch.setattr(wc, "unprotect_dpapi_hex", lambda _path: "isolated-test-secret")
    monkeypatch.setattr(host, "_authenticate", lambda *_args: {})

    def command(_command, args, **_kwargs):
        assert args[0] == "send"
        sent.append(Envelope.from_dict(wc._read_object(Path(args[args.index("--envelope") + 1]), "sent")))
        return {"status": "started", "message_id": sent[-1].message_id}

    monkeypatch.setattr(wc, "_run_json_command", command)
    return host.complete(source), sent


def bind_reader(tmp_path, monkeypatch, envelope, normalized):
    identity = {"run_id": envelope.run_id, "cell_id": envelope.cell_id,
                "message_id": envelope.message_id, "native_request_sha256": "c" * 64}
    receipt = write_json(tmp_path / "native-start.received.json", {
        **identity, "native_task": {"id": "isolated-checker"}})
    index = write_json(tmp_path / "evidence-index.json", {
        **identity, "native_task_id": "isolated-checker", "evidence": normalized["evidence"],
        "evidence_gaps": normalized.get("evidence_gaps", [])})
    monkeypatch.setenv("SLK_NATIVE_START_RECEIPT", str(receipt))
    monkeypatch.setenv("SLK_CHECKER_EVIDENCE_INDEX", str(index))
    monkeypatch.setenv("SLK_CHECKER_EVIDENCE_INDEX_SHA256", wc._sha256(index))
    return load_ocrv("slk_checker_decision.py")


@pytest.mark.parametrize("with_bytes", [False, True])
def test_frozen_external_original_reaches_real_indexed_reader_without_length_limit(tmp_path, monkeypatch, with_bytes):
    host, source, incoming, original, ref = material_host(tmp_path, with_bytes=with_bytes)
    worker_bytes = (source / "worker-result.json").read_bytes()
    incoming_bytes = (source / "envelope.json").read_bytes()
    unrelated = tmp_path / "not-declared.md"
    unrelated.write_text("Do not infer this adjacent file is review material", encoding="utf-8")
    receipt, sent = deliver(host, source, monkeypatch)
    assert receipt["status"] == "OUTPUT_DELIVERED"
    assert len(sent) == 1 and sent[0].payload["evidence_refs"] == [ref]
    assert (source / "worker-result.json").read_bytes() == worker_bytes
    assert (source / "envelope.json").read_bytes() == incoming_bytes
    assert host.binding["cells"][0]["payload"] == incoming.payload
    request = OcrvAdapter()._candidate_request(sent[0])
    assert request["evidence_refs"] == [ref]
    adapter = load_ocrv("slk_checker_adapter.py")
    normalized = adapter._validate_request(request)
    assert normalized["evidence_refs"] == [ref]
    assert normalized["evidence_gaps"] == []
    paths = [item["path"] for item in normalized["evidence"]]
    assert str(original) in paths and str(unrelated) not in paths
    assert str(source / "worker-result.json") in paths
    reader = bind_reader(tmp_path, monkeypatch, sent[0], normalized)
    read = reader.read_evidence(paths.index(str(original)))
    assert len(read["text"]) > 8000
    assert read["text"] == original.read_bytes().decode("utf-8")
    assert read["sha256"] == ref["sha256"] and read["eof"] is True
    original.write_text("later replacement", encoding="utf-8")
    with pytest.raises(ValueError):
        reader.read_evidence(paths.index(str(original)))


@pytest.mark.parametrize("damage", ["missing", "changed", "bytes"])
@pytest.mark.parametrize("when", ["before-output", "after-output"])
def test_material_gap_never_withholds_worker_output_or_reapproves_new_bytes(tmp_path, monkeypatch, damage, when):
    host, source, incoming, original, ref = material_host(tmp_path)
    before = (source / "worker-result.json").read_bytes()

    def damage_original():
        if damage == "missing":
            original.unlink()
        elif damage == "changed":
            original.write_text("unfrozen replacement", encoding="utf-8")
        else:
            ref["bytes"] += 1

    if when == "before-output":
        damage_original()
        # Fresh process loading an already-started Run must still deliver output.
        host = RoleHost(host.binding, host.digest)
    receipt, sent = deliver(host, source, monkeypatch)
    if when == "after-output":
        damage_original()
        if damage == "bytes":
            # Simulate an invalid optional byte count already in the frozen request.
            sent[0].payload["evidence_refs"][0]["bytes"] += 1
    assert receipt["status"] == "OUTPUT_DELIVERED"
    assert (source / "worker-result.json").read_bytes() == before
    request = OcrvAdapter()._candidate_request(sent[0])
    adapter = load_ocrv("slk_checker_adapter.py")
    normalized = adapter._validate_request(request)
    assert normalized["evidence_refs"][0]["sha256"] == ref["sha256"]
    assert len(normalized["evidence_gaps"]) == 1
    gap = normalized["evidence_gaps"][0]
    assert gap["path"] == str(original) and gap["sha256"] == ref["sha256"]
    assert gap["reason"] == ("UNAVAILABLE" if damage == "missing" else "CHANGED")
    paths = [item["path"] for item in normalized["evidence"]]
    assert str(original) not in paths
    assert str(source / "worker-result.json") in paths
    background = adapter._background(normalized)
    request_path = write_json(tmp_path / "indexed-request.json", request)
    adapter._index_materials(normalized, request_path, tmp_path, "gap-check", {"invocations": []})
    catalog = wc._read_object(tmp_path / "material-catalog.json", "complete material catalog")
    assert catalog["evidence_gaps"] == [gap]
    assert catalog["evidence_refs"] == normalized["evidence_refs"]
    assert "slk_read_evidence(1)" in background
    assert json.dumps(gap, ensure_ascii=False, sort_keys=True) not in background
    assert "do not claim whole-CELL PASS" in background
    reader = bind_reader(tmp_path, monkeypatch, sent[0], normalized)
    assert reader.read_evidence(paths.index(str(source / "worker-result.json")))["text"] == before.decode("utf-8")


@pytest.mark.parametrize("damage", ["missing", "changed", "bytes"])
def test_new_worker_dispatch_checks_frozen_refs_but_started_output_is_not_blocked(tmp_path, monkeypatch, damage):
    host, source, incoming, original, ref = material_host(tmp_path)
    if damage == "missing": original.unlink()
    elif damage == "changed": original.write_text("unfrozen", encoding="utf-8")
    else: ref["bytes"] += 1
    monkeypatch.setattr(host, "projection", lambda: {"summary": {"state": "running"}})
    with pytest.raises(wc.CompletionError) as failure:
        host.validate_native_dispatch(host.endpoint("worker"), incoming, tmp_path / "new-attempts")
    assert failure.value.error_code == "FROZEN_EVIDENCE_UNAVAILABLE"
    host.validate_native_dispatch(host.endpoint("worker"), incoming, source.parent.parent)
    assert deliver(host, source, monkeypatch)[0]["status"] == "OUTPUT_DELIVERED"


@pytest.mark.parametrize("damage", ["not-array", "relative", "bad-hash", "no-hash", "extra", "bool-bytes", "negative-bytes", "duplicate"])
def test_frozen_material_reference_shape_is_closed(tmp_path, damage):
    host, source, incoming = prepared_host(tmp_path)
    ref = {"path": str(source / "worker-result.json"), "sha256": "a" * 64}
    refs = [ref]
    if damage == "not-array": refs = ref
    elif damage == "relative": ref["path"] = "relative.md"
    elif damage == "bad-hash": ref["sha256"] = "unknown"
    elif damage == "no-hash": del ref["sha256"]
    elif damage == "extra": ref["auto_discover"] = True
    elif damage == "bool-bytes": ref["bytes"] = True
    elif damage == "negative-bytes": ref["bytes"] = -1
    else: refs.append(dict(ref))
    with pytest.raises(ValueError):
        RoleHost({**host.binding, "cells": [{**host.binding["cells"][0], "evidence_refs": refs}]}, "b" * 64)


def test_role_host_schema_accepts_optional_frozen_refs_and_old_binding(tmp_path):
    import jsonschema
    host, _, _, _, _ = material_host(tmp_path)
    schema = json.loads((Path(__file__).parents[2] / "docs/contracts/slk-role-host.schema.json").read_text())
    jsonschema.validate(host.binding, schema)
    del host.binding["cells"][0]["evidence_refs"]
    jsonschema.validate(host.binding, schema)


@pytest.mark.parametrize("with_bytes", [False, True])
@pytest.mark.parametrize("legacy_capacity", [False, True])
def test_ocrv_request_schema_accepts_frozen_material_producer_and_old_request(tmp_path, monkeypatch, with_bytes, legacy_capacity):
    import jsonschema
    host, source, _, _, ref = material_host(tmp_path, with_bytes=with_bytes)
    _, sent = deliver(host, source, monkeypatch)
    request = OcrvAdapter()._candidate_request(sent[0])
    if legacy_capacity:
        request["capacity"].update({"max_background_characters": 8000,
            "max_background_bytes": 24000, "max_changed_lines": 1000, "max_segment_paths": 10})
    assert request["evidence_refs"] == [ref]
    schema = json.loads((Path(__file__).parents[2] / "docs/contracts/slk-ocrv-d1-preflight.schema.json").read_text())
    jsonschema.validate(request, schema)
    load_ocrv("slk_checker_adapter.py")._validate_request(request)
    del request["evidence_refs"]
    jsonschema.validate(request, schema)


@pytest.mark.parametrize("damage", ["missing-execution-field", "partial-legacy", "extra"])
def test_ocrv_capacity_schema_and_consumer_reject_malformed_shape(tmp_path, monkeypatch, damage):
    import jsonschema
    host, source, _, _, _ = material_host(tmp_path)
    _, sent = deliver(host, source, monkeypatch)
    request = OcrvAdapter()._candidate_request(sent[0])
    if damage == "missing-execution-field":
        del request["capacity"]["timeout_minutes"]
    elif damage == "partial-legacy":
        request["capacity"]["max_background_characters"] = 8000
    else:
        request["capacity"]["undocumented_evidence_limit"] = 8000
    schema = json.loads((Path(__file__).parents[2] / "docs/contracts/slk-ocrv-d1-preflight.schema.json").read_text())
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(request, schema)
    with pytest.raises(ValueError):
        load_ocrv("slk_checker_adapter.py")._validate_request(request)


@pytest.mark.parametrize("damage", ["not-array", "not-object", "no-path", "empty-path", "no-hash", "bad-hash", "extra", "bool-bytes", "negative-bytes", "duplicate"])
def test_ocrv_request_schema_keeps_frozen_material_refs_closed(tmp_path, monkeypatch, damage):
    import jsonschema
    host, source, _, _, _ = material_host(tmp_path)
    _, sent = deliver(host, source, monkeypatch)
    request = OcrvAdapter()._candidate_request(sent[0])
    ref = request["evidence_refs"][0]
    if damage == "not-array": request["evidence_refs"] = ref
    elif damage == "not-object": request["evidence_refs"] = [ref["path"]]
    elif damage == "no-path": del ref["path"]
    elif damage == "empty-path": ref["path"] = ""
    elif damage == "no-hash": del ref["sha256"]
    elif damage == "bad-hash": ref["sha256"] = "unknown"
    elif damage == "extra": ref["auto_discover"] = True
    elif damage == "bool-bytes": ref["bytes"] = True
    elif damage == "negative-bytes": ref["bytes"] = -1
    else: request["evidence_refs"].append(dict(ref))
    schema = json.loads((Path(__file__).parents[2] / "docs/contracts/slk-ocrv-d1-preflight.schema.json").read_text())
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(request, schema)


def test_material_drift_does_not_change_original_output_message_on_retry(tmp_path, monkeypatch):
    host, source, _, original, ref = material_host(tmp_path)
    first, sent = deliver(host, source, monkeypatch)
    output = (source / "role-host/output.json").read_bytes()
    outgoing = (source / "role-host/output-envelope.json").read_bytes()
    original.write_text("different material after transport failure", encoding="utf-8")
    second, retried = deliver(host, source, monkeypatch)
    assert first["message_id"] == second["message_id"]
    assert (source / "role-host/output.json").read_bytes() == output
    assert (source / "role-host/output-envelope.json").read_bytes() == outgoing
    assert retried[0].payload["evidence_refs"] == [ref]


def test_frozen_ref_cannot_be_reapproved_via_legacy_evidence_files_overlap(tmp_path, monkeypatch):
    host, source, _, original, ref = material_host(tmp_path)
    _, sent = deliver(host, source, monkeypatch)
    request = OcrvAdapter()._candidate_request(sent[0])
    request["evidence_files"].append(str(original))
    original.write_text("changed but same explicit legacy path", encoding="utf-8")
    normalized = load_ocrv("slk_checker_adapter.py")._validate_request(request)
    assert all(item["path"] != str(original) for item in normalized["evidence"])
    assert normalized["evidence_gaps"][0]["sha256"] == ref["sha256"]


@pytest.mark.parametrize("damage", ["missing", "changed"])
@pytest.mark.parametrize("path_alias", [False, True])
def test_frozen_legacy_overlap_reaches_consumer_gap_through_producer(tmp_path, monkeypatch, damage, path_alias):
    host, source, _, original, ref = material_host(tmp_path)
    _, sent = deliver(host, source, monkeypatch)
    legacy_path = f"{original.parent}/./{original.name}" if path_alias else str(original)
    sent[0].payload["evidence_files"].append(legacy_path)
    if damage == "missing": original.unlink()
    else: original.write_text("unfrozen legacy replacement", encoding="utf-8")
    request = OcrvAdapter()._candidate_request(sent[0])
    assert request["evidence_refs"] == [ref]
    assert legacy_path in request["evidence_files"]
    normalized = load_ocrv("slk_checker_adapter.py")._validate_request(request)
    assert normalized["evidence_gaps"][0]["reason"] == ("UNAVAILABLE" if damage == "missing" else "CHANGED")
    assert normalized["evidence_gaps"][0]["sha256"] == ref["sha256"]
    assert all(Path(item["path"]).resolve() != original.resolve() for item in normalized["evidence"])
    assert any(item["path"] == str(source / "worker-result.json") for item in normalized["evidence"])


@pytest.mark.parametrize("frozen_ref", ["undeclared", "unrelated"])
def test_missing_legacy_file_reaches_catalog_as_honest_unavailable_gap(tmp_path, monkeypatch, frozen_ref):
    host, source, _, original, _ = material_host(tmp_path)
    _, sent = deliver(host, source, monkeypatch)
    payload = sent[0].payload
    original.unlink()
    payload["evidence_files"].append(str(original))
    if frozen_ref == "undeclared":
        del payload["evidence_refs"]
    else:
        payload["evidence_refs"][0]["path"] = str(tmp_path / "different-original.md")
    request = OcrvAdapter()._candidate_request(sent[0])
    adapter = load_ocrv("slk_checker_adapter.py")
    normalized = adapter._validate_request(request)
    gaps = normalized["evidence_gaps"]
    assert len(gaps) == (1 if frozen_ref == "undeclared" else 2)
    assert all(gap["reason"] == "UNAVAILABLE" for gap in gaps)
    assert any(gap["path"] == str(original) for gap in gaps)
    assert all(item["path"] != str(original) for item in normalized["evidence"])
    assert any(item["path"] == str(source / "worker-result.json") for item in normalized["evidence"])
    request_path = write_json(tmp_path / "indexed-request.json", request)
    adapter._index_materials(normalized, request_path, tmp_path, "legacy-gap", {"invocations": []})
    catalog = wc._read_object(tmp_path / "material-catalog.json", "honest legacy material gaps")
    assert catalog["evidence_gaps"] == gaps
    assert "do not claim whole-CELL PASS" in adapter._background(normalized)


@pytest.mark.parametrize("damage", ["no-hash", "bad-hash", "extra", "relative", "bool-bytes", "duplicate"])
def test_missing_legacy_file_does_not_bypass_frozen_ref_shape_validation(tmp_path, monkeypatch, damage):
    host, source, _, original, _ = material_host(tmp_path)
    _, sent = deliver(host, source, monkeypatch)
    payload = sent[0].payload
    original.unlink()
    payload["evidence_files"].append(str(original))
    ref = payload["evidence_refs"][0]
    if damage == "no-hash": del ref["sha256"]
    elif damage == "bad-hash": ref["sha256"] = "unknown"
    elif damage == "extra": ref["auto_discover"] = True
    elif damage == "relative": ref["path"] = original.name
    elif damage == "bool-bytes": ref["bytes"] = True
    else: payload["evidence_refs"].append(dict(ref))
    with pytest.raises(AdapterError) as failure:
        OcrvAdapter()._candidate_request(sent[0])
    assert failure.value.error_code == "OCRV_PAYLOAD_INVALID"


def test_management_supplement_does_not_replace_frozen_refs(tmp_path, monkeypatch):
    host, source, _, original, ref = material_host(tmp_path)
    _, sent = deliver(host, source, monkeypatch)
    request = OcrvAdapter()._candidate_request(sent[0])
    worker_report = source / "worker-result.json"
    request["management_context"] = {"management_action": "SUPPLY_EVIDENCE",
        "management_summary": "Read the original Worker report without replacing the frozen Main contract.",
        "management_evidence_refs": [{"path": str(worker_report), "sha256": wc._sha256(worker_report)}]}
    normalized = load_ocrv("slk_checker_adapter.py")._validate_request(request)
    assert normalized["evidence_refs"] == [ref]
    assert normalized["management_context"] == request["management_context"]


@pytest.mark.parametrize("damage", ["missing", "changed", None])
def test_native_run_publishes_pinned_index_and_gap_manifest_for_real_reader(tmp_path, monkeypatch, damage):
    host, source, _, original, ref = material_host(tmp_path)
    _, sent = deliver(host, source, monkeypatch)
    request_path = write_json(tmp_path / "ocrv-request.json", OcrvAdapter()._candidate_request(sent[0]))
    if damage == "missing": original.unlink()
    elif damage == "changed": original.write_text("unfrozen replacement", encoding="utf-8")
    adapter = load_ocrv("slk_checker_adapter.py")
    native_root = tmp_path / "isolated-native"
    native_root.mkdir()
    native_receipt = native_root / "native-start.received.json"
    context = {"adapter": "ocrv-checker", "run_id": sent[0].run_id, "cell_id": sent[0].cell_id,
        "message_id": sent[0].message_id, "request_sha256": sent[0].payload_sha256,
        "native_request_sha256": wc._sha256(request_path)}
    monkeypatch.setenv("SLK_NATIVE_START_RECEIPT", str(native_receipt))
    monkeypatch.setenv("SLK_NATIVE_START_CONTEXT", json.dumps(context))
    monkeypatch.setattr(adapter, "_artifact_root", lambda *_: ("isolated-checker", native_root))
    monkeypatch.setattr(adapter, "_discover_capabilities", lambda *_: {"invocations": []})
    monkeypatch.setattr(adapter, "_child_environment", lambda: {})
    monkeypatch.setattr(adapter, "_session_directory", lambda *_: native_root)
    # Real process and native receipt/index publication, without a model/service.
    monkeypatch.setattr(adapter, "_review_args", lambda *_: [sys.executable, "-c", "import time; time.sleep(0.2)"])
    output = native_root / "ocrv-result.json"
    assert adapter.run(request_path, output) == 0
    index = native_root / "evidence-index.json"
    indexed = wc._read_object(index, "actual native evidence index")
    assert indexed["evidence_refs"] == [ref]
    assert len(indexed["evidence_gaps"]) == (1 if damage else 0)
    assert wc._read_object(output, "result")["verdict"] is None
    monkeypatch.setenv("SLK_CHECKER_EVIDENCE_INDEX", str(index))
    monkeypatch.setenv("SLK_CHECKER_EVIDENCE_INDEX_SHA256", wc._sha256(index))
    reader = load_ocrv("slk_checker_decision.py")
    paths = [item["path"] for item in indexed["evidence"]]
    if damage:
        assert str(original) not in paths
        assert indexed["evidence_gaps"][0]["sha256"] == ref["sha256"]
        assert "Frozen material gaps" in (native_root / "d1-background.md").read_text(encoding="utf-8")
    else:
        assert reader.read_evidence(paths.index(str(original)))["text"] == original.read_bytes().decode("utf-8")
    assert reader.read_evidence(paths.index(str(source / "worker-result.json")))["eof"] is True


@pytest.mark.parametrize("damage", ["not-array", "not-object", "relative", "bad-hash", "no-hash", "extra", "bool-bytes", "negative-bytes", "duplicate"])
def test_index_consumer_rejects_malformed_frozen_refs(tmp_path, monkeypatch, damage):
    host, source, _, _, ref = material_host(tmp_path)
    _, sent = deliver(host, source, monkeypatch)
    request = OcrvAdapter()._candidate_request(sent[0])
    ref = request["evidence_refs"][0]
    if damage == "not-array": request["evidence_refs"] = ref
    elif damage == "not-object": request["evidence_refs"] = [ref["path"]]
    elif damage == "relative": ref["path"] = "relative.md"
    elif damage == "bad-hash": ref["sha256"] = "unknown"
    elif damage == "no-hash": del ref["sha256"]
    elif damage == "extra": ref["auto_discover"] = True
    elif damage == "bool-bytes": ref["bytes"] = True
    elif damage == "negative-bytes": ref["bytes"] = -1
    else: request["evidence_refs"].append(dict(ref))
    with pytest.raises(ValueError):
        load_ocrv("slk_checker_adapter.py")._validate_request(request)


def test_explicit_refs_do_not_bypass_existing_private_diagnostics_filter(tmp_path, monkeypatch):
    host, source, _, _, _ = material_host(tmp_path)
    _, sent = deliver(host, source, monkeypatch)
    request = OcrvAdapter()._candidate_request(sent[0])
    private = tmp_path / "thinking.txt"
    private.write_text("isolated diagnostic placeholder", encoding="utf-8")
    request["evidence_refs"] = [{"path": str(private), "sha256": wc._sha256(private)}]
    normalized = load_ocrv("slk_checker_adapter.py")._validate_request(request)
    assert all(item["path"] != str(private) for item in normalized["evidence"])
    assert normalized["evidence_gaps"][0]["reason"] == "PRIVATE_DIAGNOSTIC"


def test_valid_frozen_refs_allow_fresh_worker_dispatch(tmp_path, monkeypatch):
    host, _, incoming, _, _ = material_host(tmp_path)
    monkeypatch.setattr(host, "projection", lambda: {"summary": {"state": "running"}})
    host.validate_native_dispatch(host.endpoint("worker"), incoming, tmp_path / "new-attempts")


def test_subsequent_cell_supports_frozen_refs_without_changing_next_payload(tmp_path):
    import jsonschema
    host, source, incoming, _, ref = material_host(tmp_path)
    payload = {"cell_id": "CELL-002", "cell_ordinal": 2, "required_cell_count": 2,
        "task": "Implement frozen second CELL", "d1_criteria": ["Independent acceptance"],
        "root_record_path": str(source / "envelope.json")}
    binding = {**host.binding, "cells": [*host.binding["cells"],
        {"go_id": incoming.go_id, "cell_id": "CELL-002", "payload": payload, "evidence_refs": [ref]}]}
    prepared = RoleHost(binding, "c" * 64)
    schema = json.loads((Path(__file__).parents[2] / "docs/contracts/slk-role-host.schema.json").read_text())
    jsonschema.validate(prepared.binding, schema)
    assert prepared.binding["cells"][1]["payload"] == payload
