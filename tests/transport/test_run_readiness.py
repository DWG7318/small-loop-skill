from __future__ import annotations

import copy
import hashlib
import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

from slk_transport.run_readiness import (
    evaluate_conformance_sample_admission,
    evaluate_new_run_admission,
    evaluate_run_admission,
    evaluate_run_readiness,
    seal_normal_chain_source,
)
from slk_transport.contracts import canonical_json_sha256
from slk_transport.native_activity import make_native_start
from slk_transport import worker_completion as wc
from test_contracts import endpoint_value, envelope_value


REQUIRED_OPTIONS = ("Ponytail", "RTK", "Probe CLI")
REQUIRED_LEGS = (
    ("SETUP_TO_CHECKER", "supervisor", "checker"),
    ("CELL_TO_WORKER", "checker", "worker"),
    ("CANDIDATE_TO_CHECKER", "worker", "checker"),
    ("D1_FAIL_TO_SUPERVISOR", "checker", "supervisor"),
    ("REWORK_TO_WORKER", "supervisor", "worker"),
    ("D2_READY_TO_SUPERVISOR", "checker", "supervisor"),
    ("ANOMALY_TO_SUPERVISOR", "overwatcher", "supervisor"),
)


def write_json(path: Path, value: object) -> Path:
    path.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")
    return path


def _request(tmp_path: Path, *, legacy_echo=False, run_id="RUN-READINESS-A", method_version="4.4.2") -> dict[str, object]:
    workspace = tmp_path / "workspace"
    workspace.mkdir(exist_ok=True)
    endpoint = tmp_path / "endpoint.json"
    endpoint.write_text("{}\n", encoding="utf-8")
    skill = tmp_path / "SKILL.md"
    skill.write_text("# role\n", encoding="utf-8")
    capabilities = {}
    for runtime, events in (
        ("dsh", ["agent/status", "session/event"]),
        ("ocrv", ["review/progress", "task/status"]),
        ("lcas", ["session/status", "observation/cycle"]),
    ):
        capability = tmp_path / f"{runtime}-native-activity.json"
        capability.write_text(
            json.dumps(
                {
                    "schema_version": "slk.native-activity-capability/v1",
                    "method_version": "4.4.0",
                    "runtime": runtime,
                    "read_only_observation": True,
                    "model_call_required": False,
                    "native_events": events,
                }
            ),
            encoding="utf-8",
        )
        capabilities[runtime] = str(capability)
    roles = []
    for role, runtime, model in (
        ("supervisor", "codex", "gpt-6.1-sol"),
        ("worker", "dsh", "deepseek-v4-flash"),
        ("checker", "ocrv", "qwen3.8-max"),
        ("overwatcher", "lcas", "gpt-6-luna"),
    ):
        roles.append(
            {
                "role": role,
                "role_instance_id": f"{run_id}-{role}",
                "expected_runtime": runtime,
                "actual_runtime": runtime,
                "expected_model": model,
                "actual_model": model,
                "adapter_command": [sys.executable, "--version"],
                "endpoint_path": str(endpoint),
                "workspace_root": str(workspace),
                "context_capacity": 100_000,
                "task_context_estimate": 10_000,
                "required_skills": [str(skill)],
                "required_tools": [sys.executable],
                "native_activity_capability": capabilities.get(runtime),
                "tool_update_status": "CURRENT",
            }
        )
    bi_receipt = write_json(
        tmp_path / "bi-open.json",
        {
            "schema_version": "slk.bi-open-readiness/v1",
            "method_version": method_version,
            "run_id": run_id,
            "bi_version": "1.1.1" if method_version in {"4.4.3", "4.4.4", "4.4.5"} else "1.1.0",
            "device_id": "device-a",
            "visible": True,
            "evidence_sha256": "a" * 64,
        },
    )
    temporal_attempt_root = tmp_path / "temporal-attempts"
    temporal_attempt_root.mkdir(exist_ok=True)
    temporal_identity = write_json(tmp_path / "temporal-workflow-identity.json", {
        "schema_version": "slk.temporal-workflow-identity/v1", "run_id": run_id,
        "address": "127.0.0.1:7233", "task_queue": "slk-test",
        "start_workflow_id": f"slk-start-{run_id}",
        "start_run_id": "11111111-1111-4111-8111-111111111111",
        "run_workflow_id": f"slk-run-{run_id}",
        "run_run_id": "22222222-2222-4222-8222-222222222222",
        "startup_fingerprint": "b" * 64,
    })
    temporal_receipt = write_json(
        tmp_path / "temporal-ready.json",
        {
            "schema_version": "slk.temporal-readiness/v2",
            "method_version": method_version,
            "run_id": run_id,
            "status": "READY",
            "service_mode": "SHARED_LOCAL",
            "workflow_templates": ["SLK.Start", "SLK.Run"],
            "client_command": [sys.executable, "-m", "slk_temporal.delivery_client"],
            "workflow_identity": {"path": str(temporal_identity),
                                  "sha256": hashlib.sha256(temporal_identity.read_bytes()).hexdigest()},
            "attempt_root": str(temporal_attempt_root.resolve()),
            "evidence_sha256": "b" * 64,
        },
    )
    rehearsal = write_json(
        tmp_path / "communication-rehearsal.json",
        {
            "schema_version": "slk.communication-rehearsal/v1",
            "method_version": "4.4.0",
            "run_id": run_id,
            "status": "PASS",
            "legs": [
                {
                    "leg_id": leg_id,
                    "sender_role": sender,
                    "receiver_role": receiver,
                    "sent_receipt_sha256": "c" * 64,
                    "receiver_started_sha256": "d" * 64,
                    "response_receipt_sha256": "e" * 64,
                }
                for leg_id, sender, receiver in REQUIRED_LEGS
            ],
        },
    )
    request = {
        "schema_version": "slk.run-readiness-request/v1",
        "run_id": run_id,
        "plan_revision": 1,
        "roles": roles,
        "bi_open_receipt": str(bi_receipt),
        "temporal_readiness_receipt": str(temporal_receipt),
        "communication_rehearsal": str(rehearsal),
        "optional_features": [
            {"name": name, "decision": "OFF", "owner_evidence_ref": f"owner:{name}"}
            for name in REQUIRED_OPTIONS
        ],
    }
    if not legacy_echo:
        _attach_verified_rehearsal(tmp_path, request, method_version=method_version)
    return request


@pytest.fixture(autouse=True)
def isolated_consumer_boundary(monkeypatch):
    # Contract tests do not contact production state or consume real secrets.
    # Real Windows DPAPI + state binary tests live in test_sealed_role_credentials.
    monkeypatch.setattr(wc, "unprotect_dpapi_hex", lambda p: "isolated-test-credential")
    def authenticate(command, args, **kwargs):
        if args[0] == "run":
            run_id = args[2]
            return {"schema_version": "slk.bi.run/v1", "run_id": run_id,
                "summary": {"run_id": run_id, "slk_version": "4.4.2", "current_plan_revision": 1},
                "runtime_snapshot": {"run_id": run_id, "method_version": "4.4.2", "plan_revision": 1,
                    "runtime_revision": 7, "token_sequence": 1,
                    "token_holder_role_instance_id": f"{run_id}-supervisor", "latest_message_id": None},
                "roles": [{"role": "supervisor", "role_instance_id": f"{run_id}-supervisor", "lifecycle": "active"}],
                "token_history": [{"event_type": "TOKEN_CREATED", "token_sequence": 1,
                    "to_role_instance_id": f"{run_id}-supervisor", "from_role_instance_id": None,
                    "message_id": None, "go_id": None, "cell_id": None}],
                "events": [], "_slk_command": {"process_exit": 0}}
        return {"status": "authenticated", "run_id": args[2], "role_instance_id": args[4],
                "role": args[4].rsplit("-", 1)[1], "runtime_revision": 7}
    monkeypatch.setattr(wc, "_run_json_command", authenticate)


def _attach_verified_rehearsal(root, request, *, method_version="4.4.2"):
    """Generated artifact fixtures validate joins, not a real-role acceptance claim."""
    def proof(name, value):
        path = write_json(root / f"{name}.json", value)
        return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    run_id = request["run_id"]
    roles, consumers, endpoints = {}, {}, {}
    registered = {r["role"]: r for r in request["roles"]}
    for role, row in registered.items():
        sealed = root / f"{role}.dpapi"
        sealed.write_text("synthetic test blob", encoding="ascii")
        consumers[role] = proof(f"consumer-{role}", {"status": "SEALED_ROLE_VERIFIED", "run_id": run_id,
            "role": role, "role_instance_id": row["role_instance_id"], "sealed_path": str(sealed),
            "sealed_sha256": hashlib.sha256(sealed.read_bytes()).hexdigest(), "runtime_revision": 7})
        if role == "overwatcher":
            continue
        endpoint = endpoint_value(role=role, run_id=run_id, version=1)
        endpoint["role_instance_id"] = row["role_instance_id"]
        ref = proof(f"endpoint-{role}", endpoint)
        row["endpoint_path"] = ref["path"]
        endpoints[role] = ref
        roles[role] = {"endpoint_path": ref["path"], "endpoint_sha256": ref["sha256"], "credential_path": str(sealed)}
    worker_payload = {"cell_id": "CELL-001", "cell_ordinal": 1, "required_cell_count": 1,
        "task": "sample", "d1_criteria": ["sample test passes"], "root_record_path": str(root / "SKILL.md")}
    temporal_receipt = json.loads(Path(request["temporal_readiness_receipt"]).read_text())
    temporal = {"client_command": temporal_receipt["client_command"],
        "workflow_identity_path": temporal_receipt["workflow_identity"]["path"],
        "workflow_identity_sha256": temporal_receipt["workflow_identity"]["sha256"],
        "attempt_root": temporal_receipt["attempt_root"]}
    state_command = root / "slk-state.exe"
    state_command.write_bytes(b"isolated state fixture")
    (root / "slk-bi-query.exe").write_bytes(b"isolated query fixture")
    binding = proof("host-binding", {"schema_version": "slk.role-host/v2", "run_id": run_id, "plan_revision": 1,
        "state_command": [str(state_command)], "transport_command": ["isolated-transport"], "roles": roles,
        "cells": [{"go_id": "GO-001", "cell_id": "CELL-001", "payload": worker_payload}],
        "d2_criteria": ["one accepted CELL"], "temporal": temporal})
    kinds = ["CELL_DISPATCH", "WORKER_TASK", "CANDIDATE_READY", "D1_FAILURE_ESCALATION", "D1_REWORK_DIRECTIVE", "D2_READY"]
    legs = []
    for index, (leg_id, sender, receiver) in enumerate(REQUIRED_LEGS):
        message_id = str(uuid.uuid5(uuid.NAMESPACE_URL, leg_id))
        payload = worker_payload
        if leg_id == "SETUP_TO_CHECKER":
            payload = {"worker_endpoint": json.loads(Path(endpoints["worker"]["path"]).read_text()),
                       "worker_payload": worker_payload}
        if leg_id == "CANDIDATE_TO_CHECKER":
            payload = {"repository": str(root / "workspace"), "candidate": {"kind": "commit", "commit": "c" * 40},
                "cell_goal": "sample", "d1_criteria": ["sample test passes"], "evidence_files": [str(root / "SKILL.md")]}
        if leg_id in {"D1_FAIL_TO_SUPERVISOR", "REWORK_TO_WORKER"}:
            payload = {"d1_failure_event_id": "d1-failed", "failed_candidate_sha256": "a" * 64, "rework_round": 1,
                       "cell_goal": "sample", "acceptance_criteria": ["sample test passes"],
                       "findings": ["sample defect"], "evidence_refs": ["sample-finding"]}
            if sender == "checker":
                payload.update(reproduction_steps=["run test"], expected_result="passes")
            else:
                payload.update(investigation_mode="STANDARD", root_cause_hypothesis="boundary error",
                               minimal_experiment="focused test", minimal_repair_scope="sample", regression_target="sample test")
        if leg_id == "D2_READY_TO_SUPERVISOR":
            payload = {"d1_event_id": "d1-passed", "required_cell_ids": ["CELL-001"], "accepted_cell_ids": ["CELL-001"],
                "final_candidate_message_id": "sample-candidate", "d2_criteria": ["sample"], "evidence_refs": ["sample-pass"]}
        envelope = envelope_value(run_id=run_id, sender_role=sender, receiver_role=receiver, receiver_endpoint_version=1)
        envelope.update(message_id=message_id, token_sequence=index + 2,
                        sender_role_instance_id=registered[sender]["role_instance_id"],
                        receiver_role_instance_id=registered[receiver]["role_instance_id"])
        if sender == "overwatcher":
            envelope = {"schema_version": "slk.ow-notification/v1", "run_id": run_id, "event_id": message_id,
                "sender_role_instance_id": registered[sender]["role_instance_id"],
                "receiver_role_instance_id": registered[receiver]["role_instance_id"], "message": "发现异常，请查验。隔离样本"}
            payload_hash, cell_id = canonical_json_sha256(envelope), "PREPARATION"
        else:
            envelope.update(payload_type=kinds[index], payload=payload, payload_sha256=canonical_json_sha256(payload))
            payload_hash, cell_id = envelope["payload_sha256"], envelope["cell_id"]
        target = json.loads(Path(endpoints[receiver]["path"]).read_text())
        env_ref = proof(f"envelope-{index}", envelope)
        start_ref = proof(f"start-{index}", make_native_start(adapter=target["adapter"], run_id=run_id,
            cell_id=cell_id, message_id=message_id, request_sha256=payload_hash, native_request_sha256="b" * 64,
            native_task_kind="isolated-contract-fixture", native_task_id=f"native-{index}", native_task_status="RUNNING", pid=os.getpid()))
        sent_ref = proof(f"accepted-{index}", {"schema_version": "slk.transport-result/v1", "message_id": message_id,
            "run_id": run_id, "adapter": target["adapter"], "status": "accepted", "native_identity": {}, "error_code": None, "evidence": []})
        commit_ref = result_ref = None
        if sender != "overwatcher":
            commit_ref = proof(f"commit-{index}", {"run_id": run_id, "go_id": "GO-001", "cell_id": cell_id,
                "plan_revision": 1, "message_id": message_id, "token_sequence": envelope["token_sequence"],
                "from_role_instance_id": envelope["sender_role_instance_id"], "to_role_instance_id": envelope["receiver_role_instance_id"],
                "endpoint_version": 1, "payload_type": envelope["payload_type"], "payload_sha256": payload_hash,
                "expected_runtime_revision": index + 7, "start_evidence": {"sha256": start_ref["sha256"],
                    "endpoint_sha256": endpoints[receiver]["sha256"], "envelope_sha256": env_ref["sha256"],
                    "message_id": message_id, "native_status": "STARTED"}})
            result_ref = proof(f"commit-result-{index}", {"status": "committed", "message_id": message_id,
                              "token_sequence": envelope["token_sequence"], "runtime_revision": index + 8})
        legs.append({"leg_id": leg_id, "sender_role": sender, "receiver_role": receiver, "endpoint": endpoints[receiver],
                     "envelope": env_ref, "sent_receipt": sent_ref, "receiver_started": start_ref,
                     "commit_request": commit_ref, "commit_result": result_ref})
    write_json(Path(request["communication_rehearsal"]), {"schema_version": "slk.communication-rehearsal/v2", "method_version": method_version,
        "run_id": run_id, "plan_revision": 1, "status": "PASS", "host_binding": binding, "sealed_role_receipts": consumers, "legs": legs})


def test_four_role_readiness_is_ready_only_when_every_fact_and_route_is_closed(
    tmp_path: Path,
) -> None:
    result = evaluate_run_readiness(_request(tmp_path))

    assert result["status"] == "READY"
    assert {item["role"] for item in result["roles"]} == {
        "supervisor",
        "worker",
        "checker",
        "overwatcher",
    }
    assert {item["status"] for item in result["roles"]} == {"READY"}
    assert result["optional_features"][0]["owner_evidence_ref"].startswith("owner:")


@pytest.mark.parametrize("method_version", ["4.4.2", "4.4.3", "4.4.4", "4.4.5"])
def test_new_run_uses_a_sealed_isolated_normal_chain_and_initial_product_boundary(tmp_path, method_version):
    source_root, current_root = tmp_path / "source", tmp_path / "current"
    source_root.mkdir()
    current_root.mkdir()
    source = _request(source_root, run_id="RUN-SOURCE", method_version=method_version)
    source_request = write_json(source_root / "readiness-request.json", source)
    source_state = source_root / "state"
    source_state.mkdir()
    (source_state / "slk.db").write_bytes(b"isolated-source-database")
    source_config = write_json(source_root / "config.json", {
        "schema_version": "slk.config/v1", "data_root": str(source_state.resolve()),
    })
    normal_chain = source_root / "normal-chain-source.json"

    sealed = seal_normal_chain_source(source_request, source_config, normal_chain)

    assert sealed["schema_version"] == "slk.normal-chain-source/v1"
    assert sealed["source_run_id"] == "RUN-SOURCE"
    assert normal_chain.is_file()
    assert sealed["method_version"] == method_version
    current = _request(current_root, run_id="RUN-CURRENT", method_version=method_version)
    packet = json.loads(Path(current["communication_rehearsal"]).read_text())
    admission = {
        "schema_version": "slk.run-admission-request/v1", "run_id": "RUN-CURRENT",
        "plan_revision": 1, "roles": current["roles"],
        "optional_features": current["optional_features"],
        "bi_open_receipt": current["bi_open_receipt"],
        "temporal_readiness_receipt": current["temporal_readiness_receipt"],
        "normal_chain_conformance": str(normal_chain),
        "current_host_binding": packet["host_binding"],
        "sealed_role_receipts": packet["sealed_role_receipts"],
    }

    result = evaluate_new_run_admission(admission)

    assert result["status"] == "READY"
    assert result["conformance_run_id"] == "RUN-SOURCE"


def _conformance_sample_admission(tmp_path: Path, monkeypatch) -> tuple[dict[str, object], Path]:
    run_id = "SLK-CONFORMANCE-BOOTSTRAP-001"
    evidence_root = tmp_path / "slk-conformance" / run_id
    evidence_root.mkdir(parents=True)
    sample_root = tmp_path / "preflight" / "seven-leg-sample"
    sample_root.mkdir(parents=True)
    sample_record = write_json(sample_root / "sample-contract.json", {
        "task": "parse one bounded sample port", "acceptance": "1..65535",
    })
    subprocess.run(["git", "init", "-q", str(sample_root)], check=True)
    subprocess.run(["git", "-C", str(sample_root), "config", "user.email", "slk-test@example.invalid"], check=True)
    subprocess.run(["git", "-C", str(sample_root), "config", "user.name", "SLK Test"], check=True)
    subprocess.run(["git", "-C", str(sample_root), "add", "sample-contract.json"], check=True)
    subprocess.run(["git", "-C", str(sample_root), "commit", "-q", "-m", "isolated sample"], check=True)
    sample_head = subprocess.run(
        ["git", "-C", str(sample_root), "rev-parse", "HEAD"], check=True,
        text=True, capture_output=True,
    ).stdout.strip()
    state_root = tmp_path / "central-state"
    state_root.mkdir()
    (state_root / "slk.db").write_bytes(b"isolated-state-fixture")
    root_record = state_root / "exports" / "sample-project" / run_id / f"SLK-RUN-{run_id}.md"
    root_record.parent.mkdir(parents=True)
    root_record.write_text(f"# {run_id}\n", encoding="utf-8")
    state_config = write_json(tmp_path / "state-config.json", {
        "schema_version": "slk.config/v1", "data_root": str(state_root.resolve()),
    })
    monkeypatch.setenv("SLK_CONFIG_PATH", str(state_config.resolve()))
    current = _request(evidence_root, run_id=run_id)
    for role in current["roles"]:
        if role["role"] == "worker":
            role["workspace_root"] = str(sample_root.resolve())
        else:
            native_root = tmp_path / "native-cwd" / role["role"]
            native_root.mkdir(parents=True)
            role["workspace_root"] = str(native_root.resolve())
    packet = json.loads(Path(current["communication_rehearsal"]).read_text())
    host_path = Path(packet["host_binding"]["path"])
    host = json.loads(host_path.read_text())
    host["cells"][0]["payload"]["root_record_path"] = str(root_record.resolve())
    write_json(host_path, host)
    packet["host_binding"]["sha256"] = hashlib.sha256(host_path.read_bytes()).hexdigest()
    contract = write_json(evidence_root / "isolation-contract.json", {
        "schema_version": "slk.conformance-sample-isolation/v1",
        "method_version": "4.4.2",
        "run_id": run_id,
        "kind": "ISOLATED_NORMAL_CHAIN_SAMPLE",
        "evidence_root": str(evidence_root.resolve()),
        "sample_workspace_root": str(sample_root.resolve()),
        "sample_head": sample_head,
        "disposable": True,
        "product_dispatch_allowed": False,
    })
    return {
        "schema_version": "slk.conformance-sample-admission-request/v1",
        "run_id": run_id,
        "plan_revision": 1,
        "roles": current["roles"],
        "optional_features": current["optional_features"],
        "bi_open_receipt": current["bi_open_receipt"],
        "temporal_readiness_receipt": current["temporal_readiness_receipt"],
        "isolation_contract": str(contract.resolve()),
        "current_host_binding": packet["host_binding"],
        "sealed_role_receipts": packet["sealed_role_receipts"],
    }, evidence_root


def test_first_real_normal_chain_source_has_an_explicit_isolated_admission(tmp_path, monkeypatch):
    admission, _sample_root = _conformance_sample_admission(tmp_path, monkeypatch)

    result = evaluate_conformance_sample_admission(admission)

    assert result["status"] == "READY"
    assert result["conformance_run_id"] is None


@pytest.mark.parametrize("damage", [
    "product-run-id", "product-dispatch", "workspace-escape", "multiple-cells",
    "evidence-escape", "wrong-parent", "fake-root-record",
])
def test_isolated_conformance_admission_cannot_be_used_as_product_dispatch(tmp_path, monkeypatch, damage):
    admission, evidence_root = _conformance_sample_admission(tmp_path, monkeypatch)
    contract_path = Path(admission["isolation_contract"])
    contract = json.loads(contract_path.read_text())
    if damage == "product-run-id":
        admission["run_id"] = "RUN-PRODUCT"
    elif damage == "product-dispatch":
        contract["product_dispatch_allowed"] = True
        write_json(contract_path, contract)
    elif damage == "workspace-escape":
        admission["roles"][1]["workspace_root"] = str(tmp_path.resolve())
    elif damage == "multiple-cells":
        host_path = Path(admission["current_host_binding"]["path"])
        host = json.loads(host_path.read_text())
        host["cells"].append(copy.deepcopy(host["cells"][0]))
        host["cells"][1]["cell_id"] = "CELL-002"
        write_json(host_path, host)
        admission["current_host_binding"]["sha256"] = hashlib.sha256(host_path.read_bytes()).hexdigest()
    elif damage == "evidence-escape":
        escaped = write_json(tmp_path / "escaped-bi.json", json.loads(Path(admission["bi_open_receipt"]).read_text()))
        admission["bi_open_receipt"] = str(escaped.resolve())
    elif damage == "wrong-parent":
        moved = tmp_path / "wrong-parent" / admission["run_id"]
        moved.mkdir(parents=True)
        contract["evidence_root"] = str(moved.resolve())
        write_json(contract_path, contract)
    else:
        host_path = Path(admission["current_host_binding"]["path"])
        host = json.loads(host_path.read_text())
        host["cells"][0]["payload"]["root_record_path"] = str(
            Path(contract["sample_workspace_root"]) / "sample-contract.json")
        write_json(host_path, host)
        admission["current_host_binding"]["sha256"] = hashlib.sha256(host_path.read_bytes()).hexdigest()

    result = evaluate_conformance_sample_admission(admission)

    assert result["status"] == "REPAIR_NEEDED"
    assert "CONFORMANCE_SAMPLE_ISOLATION_INVALID" in result["reason_codes"]


@pytest.mark.parametrize("damage", ["dirty", "remote", "head-drift"])
def test_isolated_conformance_requires_a_clean_fixed_no_remote_sample_git(tmp_path, monkeypatch, damage):
    admission, _evidence_root = _conformance_sample_admission(tmp_path, monkeypatch)
    contract_path = Path(admission["isolation_contract"])
    contract = json.loads(contract_path.read_text())
    sample_root = Path(contract["sample_workspace_root"])
    if damage == "dirty":
        (sample_root / "dirty.txt").write_text("dirty", encoding="utf-8")
    elif damage == "remote":
        subprocess.run([
            "git", "-C", str(sample_root), "remote", "add", "origin",
            "https://example.invalid/product.git",
        ], check=True)
    else:
        contract["sample_head"] = "0" * len(contract["sample_head"])
        write_json(contract_path, contract)

    result = evaluate_conformance_sample_admission(admission)

    assert result["status"] == "REPAIR_NEEDED"
    assert "CONFORMANCE_SAMPLE_ISOLATION_INVALID" in result["reason_codes"]


def test_product_admission_cannot_substitute_an_isolation_contract(tmp_path, monkeypatch):
    admission, _sample_root = _conformance_sample_admission(tmp_path, monkeypatch)
    admission["schema_version"] = "slk.run-admission-request/v1"

    with pytest.raises(ValueError, match="exact field set"):
        evaluate_new_run_admission(admission)


def test_normal_chain_seal_rejects_a_non_ready_source(tmp_path):
    source = _request(tmp_path, run_id="RUN-SOURCE")
    Path(source["communication_rehearsal"]).unlink()
    request_path = write_json(tmp_path / "readiness-request.json", source)
    state = tmp_path / "state"
    state.mkdir()
    (state / "slk.db").write_bytes(b"isolated-source-database")
    config = write_json(tmp_path / "config.json", {
        "schema_version": "slk.config/v1", "data_root": str(state.resolve()),
    })

    with pytest.raises(ValueError, match="READY"):
        seal_normal_chain_source(request_path, config, tmp_path / "normal-chain-source.json")


def test_inflight_admission_separates_reusable_normal_chain_from_current_run_identity(tmp_path):
    source_root = tmp_path / "source"
    current_root = tmp_path / "current"
    source_root.mkdir()
    current_root.mkdir()
    source = _request(source_root, run_id="RUN-CONFORMANCE")
    source_path = write_json(source_root / "readiness-request.json", source)
    source_rehearsal = Path(source["communication_rehearsal"])
    def proof(path):
        return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    conformance = write_json(source_root / "normal-chain-conformance.json", {
        "schema_version": "slk.normal-chain-conformance/v1", "method_version": "4.4.2",
        "status": "PASS", "source_run_id": "RUN-CONFORMANCE",
        "source_readiness_request": proof(source_path),
        "source_communication_rehearsal": proof(source_rehearsal),
    })
    current = _request(current_root, run_id="RUN-CURRENT")
    current_rehearsal = json.loads(Path(current["communication_rehearsal"]).read_text())
    Path(current["communication_rehearsal"]).unlink()
    admission = {
        "schema_version": "slk.run-admission-request/v1", "run_id": "RUN-CURRENT", "plan_revision": 1,
        "roles": current["roles"], "optional_features": current["optional_features"],
        "bi_open_receipt": current["bi_open_receipt"],
        "temporal_readiness_receipt": current["temporal_readiness_receipt"],
        "normal_chain_conformance": str(conformance),
        "current_host_binding": current_rehearsal["host_binding"],
        "sealed_role_receipts": current_rehearsal["sealed_role_receipts"],
    }

    result = evaluate_run_admission(admission)

    assert result["status"] == "READY"
    assert result["conformance_run_id"] == "RUN-CONFORMANCE"
    assert result["run_id"] == "RUN-CURRENT"
    assert not Path(current["communication_rehearsal"]).exists()

    new_run_result = evaluate_new_run_admission(admission)
    assert new_run_result["status"] == "READY"


def test_inflight_admission_checks_the_same_historical_null_boundary_as_the_real_consumer(
    tmp_path, monkeypatch,
):
    source_root, current_root = tmp_path / "source", tmp_path / "current"
    source_root.mkdir()
    current_root.mkdir()
    source = _request(source_root, run_id="RUN-CONFORMANCE")
    source_path = write_json(source_root / "readiness-request.json", source)
    def proof(path):
        return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    conformance = write_json(source_root / "normal-chain-conformance.json", {
        "schema_version": "slk.normal-chain-conformance/v1", "method_version": "4.4.2",
        "status": "PASS", "source_run_id": "RUN-CONFORMANCE",
        "source_readiness_request": proof(source_path),
        "source_communication_rehearsal": proof(Path(source["communication_rehearsal"])),
    })
    current = _request(current_root, run_id="RUN-CURRENT")
    packet = json.loads(Path(current["communication_rehearsal"]).read_text())
    admission = {"schema_version": "slk.run-admission-request/v1", "run_id": "RUN-CURRENT",
        "plan_revision": 1, "roles": current["roles"], "optional_features": current["optional_features"],
        "bi_open_receipt": current["bi_open_receipt"],
        "temporal_readiness_receipt": current["temporal_readiness_receipt"],
        "normal_chain_conformance": str(conformance), "current_host_binding": packet["host_binding"],
        "sealed_role_receipts": packet["sealed_role_receipts"]}
    registered = {row["role"]: row for row in current["roles"]}
    message_id = "c13ee3db-524e-4011-a7f3-ba02386e5599"
    projection = {"schema_version": "slk.bi.run/v1", "run_id": "RUN-CURRENT",
        "summary": {"run_id": "RUN-CURRENT", "slk_version": "4.4.2", "current_plan_revision": 1},
        "runtime_snapshot": {"run_id": "RUN-CURRENT", "method_version": "4.4.2", "plan_revision": 1,
            "runtime_revision": 15, "token_sequence": 3,
            "token_holder_role_instance_id": registered["worker"]["role_instance_id"], "latest_message_id": None},
        "token_history": [{"event_type": "TOKEN_HANDED_OFF", "message_id": message_id,
            "token_sequence": 3, "go_id": "GO-001", "cell_id": "CELL-001",
            "from_role_instance_id": registered["checker"]["role_instance_id"],
            "to_role_instance_id": registered["worker"]["role_instance_id"]}],
        "events": [{"event_id": "transport-start-cell01-t003-mcp-startup-20261004t081141z",
            "event_type": "TRANSPORT_STARTED", "corrects_event_id": None,
            "go_id": "GO-001", "cell_id": "CELL-001", "plan_revision": 1,
            "author_role_instance_id": registered["checker"]["role_instance_id"],
            "details_json": json.dumps({"message_id": message_id,
                "endpoint_sha256": "348444cc80aef5a5e330dd576b57c542364db0191d8d44ec79fad17e6b2bbaa2",
                "envelope_sha256": "19a436c76c220e91d1c9efca89bc14650b6cefcac849d1c7d596e19bfb77765d",
                "start_evidence_sha256": "521542adc90d5fd07ea14ebf34d47f559613423b01b820e6d89357ac47b2111c"})}],
        "_slk_command": {"process_exit": 0}}
    def state_call(_command, args, **_kwargs):
        if args[0] == "run":
            return copy.deepcopy(projection)
        return {"status": "authenticated", "run_id": args[2], "role_instance_id": args[4],
            "role": args[4].rsplit("-", 1)[1], "runtime_revision": 15}
    monkeypatch.setattr(wc, "_run_json_command", state_call)

    assert evaluate_run_admission(admission)["status"] == "READY"
    new_run_result = evaluate_new_run_admission(admission)
    assert new_run_result["status"] == "REPAIR_NEEDED"
    assert "NEW_RUN_INITIAL_TOKEN_REQUIRED" in new_run_result["reason_codes"]
    projection["events"][0]["details_json"] = json.dumps({"message_id": message_id,
        "endpoint_sha256": "wrong", "envelope_sha256": "wrong", "start_evidence_sha256": "wrong"})
    rejected = evaluate_run_admission(admission)
    assert rejected["status"] == "REPAIR_NEEDED"
    assert "CURRENT_TOKEN_BOUNDARY_INVALID" in rejected["reason_codes"]


def test_narrow_normal_chain_source_uses_its_own_state_database_without_changing_current_run(
    tmp_path, monkeypatch,
):
    source_root, current_root = tmp_path / "source", tmp_path / "current"
    source_root.mkdir()
    current_root.mkdir()
    source = _request(source_root, run_id="RUN-SOURCE")
    current = _request(current_root, run_id="RUN-CURRENT")

    source_state = source_root / "state"
    source_state.mkdir()
    (source_state / "slk.db").write_bytes(b"source-db")
    source_config = write_json(source_root / "config.json", {
        "schema_version": "slk.config/v1", "data_root": str(source_state.resolve()),
    })
    current_state = current_root / "state"
    current_state.mkdir()
    (current_state / "slk.db").write_bytes(b"current-db")
    current_config = write_json(current_root / "config.json", {
        "schema_version": "slk.config/v1", "data_root": str(current_state.resolve()),
    })
    monkeypatch.setenv("SLK_CONFIG_PATH", str(current_config.resolve()))

    def proof(path):
        return {"path": str(path.resolve()), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}

    source_contract = write_json(source_root / "normal-chain-source.json", {
        "schema_version": "slk.normal-chain-source/v1", "method_version": "4.4.2",
        "status": "PASS", "source_run_id": "RUN-SOURCE", "plan_revision": 1,
        "source_state_context": {
            "config_path": str(source_config.resolve()),
            "config_sha256": hashlib.sha256(source_config.read_bytes()).hexdigest(),
        },
        "source_roles": [{key: row[key] for key in (
            "role", "role_instance_id", "actual_runtime", "endpoint_path", "workspace_root"
        )} for row in source["roles"]],
        "source_communication_rehearsal": proof(Path(source["communication_rehearsal"])),
    })
    current_packet = json.loads(Path(current["communication_rehearsal"]).read_text())
    admission = {
        "schema_version": "slk.run-admission-request/v1", "run_id": "RUN-CURRENT",
        "plan_revision": 1, "roles": current["roles"],
        "optional_features": current["optional_features"],
        "bi_open_receipt": current["bi_open_receipt"],
        "temporal_readiness_receipt": current["temporal_readiness_receipt"],
        "normal_chain_conformance": str(source_contract),
        "current_host_binding": current_packet["host_binding"],
        "sealed_role_receipts": current_packet["sealed_role_receipts"],
    }
    calls = []

    def authenticate(command, args, *, state_config_path=None, **_kwargs):
        if args[0] == "run":
            run_id = args[2]
            calls.append((run_id, state_config_path, os.environ["SLK_CONFIG_PATH"]))
            return {"schema_version": "slk.bi.run/v1", "run_id": run_id,
                "summary": {"run_id": run_id, "slk_version": "4.4.2", "current_plan_revision": 1},
                "runtime_snapshot": {"run_id": run_id, "method_version": "4.4.2", "plan_revision": 1,
                    "runtime_revision": 7, "token_sequence": 1,
                    "token_holder_role_instance_id": f"{run_id}-supervisor", "latest_message_id": None},
                "roles": [{"role": "supervisor", "role_instance_id": f"{run_id}-supervisor", "lifecycle": "active"}],
                "token_history": [{"event_type": "TOKEN_CREATED", "token_sequence": 1,
                    "to_role_instance_id": f"{run_id}-supervisor", "from_role_instance_id": None,
                    "message_id": None, "go_id": None, "cell_id": None}],
                "events": [], "_slk_command": {"process_exit": 0}}
        run_id, role_instance_id = args[2], args[4]
        calls.append((run_id, state_config_path, os.environ["SLK_CONFIG_PATH"]))
        if run_id == "RUN-SOURCE" and state_config_path != str(source_config.resolve()):
            raise ValueError("source authentication used the product database")
        if run_id == "RUN-CURRENT" and (
            state_config_path is not None
            or os.environ["SLK_CONFIG_PATH"] != str(current_config.resolve())
        ):
            raise ValueError("current authentication left the product database")
        return {"status": "authenticated", "run_id": run_id,
                "role_instance_id": role_instance_id,
                "role": role_instance_id.rsplit("-", 1)[1], "runtime_revision": 7}

    monkeypatch.setattr(wc, "_run_json_command", authenticate)
    result = evaluate_run_admission(admission)

    assert result["status"] == "READY"
    assert result["conformance_run_id"] == "RUN-SOURCE"
    assert {item[0] for item in calls} == {"RUN-SOURCE", "RUN-CURRENT"}
    assert os.environ["SLK_CONFIG_PATH"] == str(current_config.resolve())

    source_config.write_text(source_config.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    drifted = evaluate_run_admission(admission)
    assert drifted["status"] == "REPAIR_NEEDED"
    assert "NORMAL_CHAIN_CONFORMANCE_INVALID" in drifted["reason_codes"]
    assert os.environ["SLK_CONFIG_PATH"] == str(current_config.resolve())


def test_inflight_admission_rejects_echo_conformance_and_missing_current_consumer(tmp_path):
    source_root = tmp_path / "source"
    current_root = tmp_path / "current"
    source_root.mkdir()
    current_root.mkdir()
    source = _request(source_root, legacy_echo=True, run_id="RUN-CONFORMANCE")
    source_path = write_json(source_root / "readiness-request.json", source)
    source_rehearsal = Path(source["communication_rehearsal"])
    def proof(path):
        return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    conformance = write_json(source_root / "normal-chain-conformance.json", {
        "schema_version": "slk.normal-chain-conformance/v1", "method_version": "4.4.2",
        "status": "PASS", "source_run_id": "RUN-CONFORMANCE",
        "source_readiness_request": proof(source_path),
        "source_communication_rehearsal": proof(source_rehearsal),
    })
    current = _request(current_root, run_id="RUN-CURRENT")
    packet = json.loads(Path(current["communication_rehearsal"]).read_text())
    packet["sealed_role_receipts"].pop("worker")
    admission = {"schema_version": "slk.run-admission-request/v1", "run_id": "RUN-CURRENT", "plan_revision": 1,
        "roles": current["roles"], "optional_features": current["optional_features"],
        "bi_open_receipt": current["bi_open_receipt"], "temporal_readiness_receipt": current["temporal_readiness_receipt"],
        "normal_chain_conformance": str(conformance), "current_host_binding": packet["host_binding"],
        "sealed_role_receipts": packet["sealed_role_receipts"]}
    assert evaluate_run_admission(admission)["status"] == "REPAIR_NEEDED"


def test_legacy_echo_hashes_are_not_normal_handoff_evidence(tmp_path):
    request = _request(tmp_path, legacy_echo=True)
    result = evaluate_run_readiness(request)
    assert result["status"] == "REPAIR_NEEDED"
    assert "COMMUNICATION_REHEARSAL_INVALID" in result["reason_codes"]


def test_temporal_ready_run_rejects_current_host_without_exact_temporal_binding(tmp_path):
    request = _request(tmp_path)
    rehearsal_path = Path(request["communication_rehearsal"])
    rehearsal = json.loads(rehearsal_path.read_text())
    host_path = Path(rehearsal["host_binding"]["path"])
    host = json.loads(host_path.read_text())
    host["schema_version"] = "slk.role-host/v1"
    host.pop("temporal")
    write_json(host_path, host)
    rehearsal["host_binding"]["sha256"] = hashlib.sha256(host_path.read_bytes()).hexdigest()
    write_json(rehearsal_path, rehearsal)

    result = evaluate_run_readiness(request)

    assert result["status"] == "REPAIR_NEEDED"
    assert "TEMPORAL_BINDING_INVALID" in result["reason_codes"]


@pytest.mark.parametrize("feature", REQUIRED_OPTIONS)
def test_enabled_optional_tool_cannot_skip_its_actual_role_entry(tmp_path, feature):
    request = _request(tmp_path)
    next(o for o in request["optional_features"] if o["name"] == feature)["decision"] = "ON"
    result = evaluate_run_readiness(request)
    assert result["status"] == "REPAIR_NEEDED"
    assert "ENABLED_OPTION_ENTRY_MISSING" in result["reason_codes"]


def test_enabled_rtk_requires_both_original_worker_and_checker_entry(tmp_path):
    request = _request(tmp_path)
    next(o for o in request["optional_features"] if o["name"] == "RTK")["decision"] = "ON"
    entry = tmp_path / "rtk.cmd"
    entry.write_text("@echo capability-fixture-only", encoding="ascii")
    for role in request["roles"]:
        if role["role"] in {"worker", "checker"}: role["required_tools"].append(str(entry))
    assert evaluate_run_readiness(request)["status"] == "READY"
    request["roles"][2]["required_tools"].remove(str(entry))
    assert evaluate_run_readiness(request)["status"] == "REPAIR_NEEDED"


@pytest.mark.parametrize("index", [0, 1, 2])
def test_normal_label_cannot_disguise_echo_only_payload(tmp_path, index):
    request = _request(tmp_path)
    path = Path(request["communication_rehearsal"])
    value = json.loads(path.read_text())
    leg = value["legs"][index]
    def replace(reference, change):
        file = Path(reference["path"])
        obj = json.loads(file.read_text())
        change(obj)
        write_json(file, obj)
        reference["sha256"] = hashlib.sha256(file.read_bytes()).hexdigest()
    echo = {"task": "reply exactly READY"}
    digest = canonical_json_sha256(echo)
    replace(leg["envelope"], lambda obj: obj.update(payload=echo, payload_sha256=digest))
    replace(leg["receiver_started"], lambda obj: obj.update(request_sha256=digest))
    def update_commit(obj):
        obj["payload_sha256"] = digest
        obj["start_evidence"].update(sha256=leg["receiver_started"]["sha256"], envelope_sha256=leg["envelope"]["sha256"])
    replace(leg["commit_request"], update_commit)
    write_json(path, value)
    assert evaluate_run_readiness(request)["status"] == "REPAIR_NEEDED"


@pytest.mark.parametrize("failure", ["missing_bytes", "changed_bytes", "missing_commit", "wrong_role",
                                     "duplicate_leg", "old_plan", "consumer_rejected", "only_accepted",
                                     "echo_payload", "ow_takes_token"])
def test_rehearsal_requires_exact_native_and_owned_commit_evidence(tmp_path, monkeypatch, failure):
    request = _request(tmp_path)
    path = Path(request["communication_rehearsal"])
    value = json.loads(path.read_text())
    leg = value["legs"][2]
    if failure == "missing_bytes":
        Path(leg["receiver_started"]["path"]).unlink()
    elif failure == "changed_bytes":
        Path(leg["receiver_started"]["path"]).write_text("{}")
    elif failure == "missing_commit":
        leg["commit_result"] = None
    elif failure == "wrong_role":
        request["roles"][1]["role_instance_id"] = "different-worker"
    elif failure == "duplicate_leg":
        value["legs"][3] = leg
    elif failure == "old_plan":
        request["plan_revision"] = 2
    elif failure == "consumer_rejected":
        monkeypatch.setattr(wc, "_run_json_command", lambda *a, **k: {"status": "rejected"})
    elif failure == "only_accepted":
        leg["receiver_started"] = leg["sent_receipt"]
    elif failure == "echo_payload":
        envelope_path = Path(leg["envelope"]["path"])
        envelope = json.loads(envelope_path.read_text())
        envelope["payload_type"] = "TRANSPORT_PROBE"
        write_json(envelope_path, envelope)
        leg["envelope"]["sha256"] = hashlib.sha256(envelope_path.read_bytes()).hexdigest()
    elif failure == "ow_takes_token":
        value["legs"][-1]["commit_result"] = leg["commit_result"]
    write_json(path, value)
    result = evaluate_run_readiness(request)
    assert result["status"] == "REPAIR_NEEDED"
    assert "COMMUNICATION_REHEARSAL_INVALID" in result["reason_codes"]


def test_missing_checker_capability_keeps_run_in_preparation(tmp_path: Path) -> None:
    request = _request(tmp_path)
    request["roles"][2]["required_tools"] = [str(tmp_path / "missing-ocrv")]

    result = evaluate_run_readiness(request)

    assert result["status"] == "REPAIR_NEEDED"
    checker = next(item for item in result["roles"] if item["role"] == "checker")
    assert checker["status"] == "REPAIR_NEEDED"
    assert "REQUIRED_TOOL_MISSING" in checker["reason_codes"]


def test_missing_overwatcher_or_failed_normal_route_rehearsal_blocks_start(tmp_path: Path) -> None:
    missing_role = _request(tmp_path)
    missing_role["roles"] = [row for row in missing_role["roles"] if row["role"] != "overwatcher"]
    with pytest.raises(ValueError, match="exactly one"):
        evaluate_run_readiness(missing_role)

    failed_route = _request(tmp_path)
    path = Path(failed_route["communication_rehearsal"])
    receipt = json.loads(path.read_text(encoding="utf-8"))
    receipt["legs"][2]["receiver_started"]["sha256"] = ""
    path.write_text(json.dumps(receipt), encoding="utf-8")
    result = evaluate_run_readiness(failed_route)
    assert result["status"] == "REPAIR_NEEDED"
    assert "COMMUNICATION_REHEARSAL_INVALID" in result["reason_codes"]


def test_tool_upgrade_need_and_missing_bi_or_temporal_proof_block_start(tmp_path: Path) -> None:
    update = _request(tmp_path)
    update["roles"][1]["tool_update_status"] = "UPDATE_REQUIRED"
    result = evaluate_run_readiness(update)
    assert result["status"] == "REPAIR_NEEDED"
    assert "TOOL_UPDATE_REQUIRED" in result["reason_codes"]

    missing = _request(tmp_path)
    Path(missing["bi_open_receipt"]).unlink()
    Path(missing["temporal_readiness_receipt"]).unlink()
    result = evaluate_run_readiness(missing)
    assert "BI_OPEN_RECEIPT_INVALID" in result["reason_codes"]
    assert "TEMPORAL_READINESS_INVALID" in result["reason_codes"]


def test_missing_or_wrong_native_activity_capability_blocks_worker_and_checker(
    tmp_path: Path,
) -> None:
    missing = _request(tmp_path)
    missing["roles"][1]["native_activity_capability"] = str(tmp_path / "missing.json")

    result = evaluate_run_readiness(missing)

    assert result["status"] == "REPAIR_NEEDED"
    worker = next(item for item in result["roles"] if item["role"] == "worker")
    assert "NATIVE_ACTIVITY_CAPABILITY_MISSING" in worker["reason_codes"]

    wrong = _request(tmp_path)
    checker_capability = Path(wrong["roles"][2]["native_activity_capability"])
    value = json.loads(checker_capability.read_text(encoding="utf-8"))
    value["runtime"] = "dsh"
    checker_capability.write_text(json.dumps(value), encoding="utf-8")

    result = evaluate_run_readiness(wrong)

    checker = next(item for item in result["roles"] if item["role"] == "checker")
    assert "NATIVE_ACTIVITY_CAPABILITY_INVALID" in checker["reason_codes"]


def test_role_context_estimate_is_advisory_not_an_admission_gate(tmp_path: Path) -> None:
    request = _request(tmp_path)
    request["roles"][1]["task_context_estimate"] = 100_001

    result = evaluate_run_readiness(request)

    assert result["status"] == "READY"
    worker = next(item for item in result["roles"] if item["role"] == "worker")
    assert worker["reason_codes"] == []
    assert worker["advisory_codes"] == ["TASK_CONTEXT_ESTIMATE_EXCEEDS_DECLARED_CAPACITY"]


@pytest.mark.parametrize("unknown", ["omit", "null"])
def test_unpublished_context_values_remain_unknown_without_blocking_readiness(tmp_path, unknown):
    from jsonschema import Draft202012Validator
    request = _request(tmp_path)
    worker = request["roles"][1]
    for field in ("context_capacity", "task_context_estimate"):
        if unknown == "omit":
            worker.pop(field)
        else:
            worker[field] = None
    schema = Path(__file__).resolve().parents[2] / "docs/contracts/slk-run-readiness.schema.json"
    Draft202012Validator(json.loads(schema.read_text())).validate(request)
    result = evaluate_run_readiness(request)
    assert result["status"] == "READY"
    assert result["roles"][1]["advisory_codes"] == ["TASK_CONTEXT_UNKNOWN"]
    worker["actual_model"] = "wrong-model"
    assert evaluate_run_readiness(request)["status"] == "INCOMPATIBLE"


@pytest.mark.parametrize("field", ["context_capacity", "task_context_estimate"])
@pytest.mark.parametrize("invalid", [0, -1, True, "unknown"])
def test_context_unknown_does_not_accept_false_numeric_facts(tmp_path, field, invalid):
    request = _request(tmp_path)
    request["roles"][1][field] = invalid
    with pytest.raises(ValueError, match="positive integer"):
        evaluate_run_readiness(request)


@pytest.mark.parametrize("method_version", ["4.4.3", "4.4.4", "4.4.5"])
@pytest.mark.parametrize("receipt_method", ["4.4.2", "4.4.3"])
def test_current_readiness_requires_actual_bi_111_even_with_legacy_receipt_label(tmp_path, receipt_method, method_version):
    request = _request(tmp_path, method_version=method_version)
    path = Path(request["bi_open_receipt"])
    receipt = json.loads(path.read_text())
    receipt.update(method_version=receipt_method, bi_version="1.1.0")
    write_json(path, receipt)
    assert "BI_OPEN_RECEIPT_INVALID" in evaluate_run_readiness(request)["reason_codes"]
    receipt["bi_version"] = "1.1.1"
    write_json(path, receipt)
    assert evaluate_run_readiness(request)["status"] == "READY"


def test_unconfirmed_or_missing_optional_feature_keeps_run_in_preparation(tmp_path: Path) -> None:
    unconfirmed = _request(tmp_path)
    unconfirmed["optional_features"][0] = {
        "name": "Ponytail",
        "decision": "UNCONFIRMED",
        "owner_evidence_ref": "",
    }
    result = evaluate_run_readiness(unconfirmed)
    assert result["status"] == "REPAIR_NEEDED"
    assert "OPTION_DECISION_REQUIRED" in result["reason_codes"]

    missing = _request(tmp_path)
    missing["optional_features"] = missing["optional_features"][:-1]
    result = evaluate_run_readiness(missing)
    assert result["status"] == "REPAIR_NEEDED"
    assert "REQUIRED_OPTION_MISSING" in result["reason_codes"]


def test_role_substitution_is_not_repairable_by_prompt(tmp_path: Path) -> None:
    request = copy.deepcopy(_request(tmp_path))
    request["roles"][2]["actual_runtime"] = "codex"

    result = evaluate_run_readiness(request)

    assert result["status"] == "INCOMPATIBLE"
    checker = next(item for item in result["roles"] if item["role"] == "checker")
    assert "RUNTIME_MISMATCH" in checker["reason_codes"]
    json.dumps(result)


def test_future_option_requires_registered_capability_not_a_free_name(tmp_path: Path) -> None:
    request = _request(tmp_path)
    request["optional_features"].append(
        {"name": "Future Tool", "decision": "UNCONFIRMED", "owner_evidence_ref": ""}
    )

    result = evaluate_run_readiness(request)

    assert result["status"] == "REPAIR_NEEDED"
    assert "OPTION_UNSUPPORTED" in result["reason_codes"]


@pytest.mark.parametrize("decision", ["ON", "OFF"])
def test_unsupported_optional_feature_is_not_an_enable_or_disable_switch(
    tmp_path: Path, decision: str
) -> None:
    request = _request(tmp_path)
    request["optional_features"].append(
        {"name": "UNREGISTERED_AUXILIARY", "decision": decision, "owner_evidence_ref": "owner:legacy"}
    )

    result = evaluate_run_readiness(request)

    assert result["status"] == "REPAIR_NEEDED"
    assert "OPTION_UNSUPPORTED" in result["reason_codes"]
    assert all(item["name"] != "UNREGISTERED_AUXILIARY" for item in result["optional_features"])


def _native_ow_request(tmp_path):
    request = _request(tmp_path)
    ow = next(r for r in request["roles"] if r["role"] == "overwatcher")
    ow["actual_runtime"] = ow["expected_runtime"] = "codex"
    ow["native_activity_capability"] = str(write_json(tmp_path / "native-ow-capability.json", {
        "schema_version": "slk.native-activity-capability/v1", "method_version": "4.4.2", "runtime": "codex",
        "read_only_observation": True, "model_call_required": False, "native_events": ["thread/status", "turn/status"]}))
    ow["endpoint_path"] = str(write_json(tmp_path / "native-ow-endpoint.json", {
        "schema_version": "slk.transport-endpoint/v1", "run_id": request["run_id"], "role": "overwatcher",
        "role_instance_id": ow["role_instance_id"], "agent_runtime": "codex", "adapter": "codex-app-server",
        "host_id": "local", "endpoint_version": 1, "state": "active", "address": {"thread_id": "registered-ow-session"}}))
    packet_path = Path(request["communication_rehearsal"])
    packet = json.loads(packet_path.read_text())
    def ref(path):
        return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    host_path = Path(packet["host_binding"]["path"])
    host = json.loads(host_path.read_text())
    endpoint_path = Path(host["roles"]["supervisor"]["endpoint_path"])
    endpoint = json.loads(endpoint_path.read_text())
    endpoint["address"]["desktop"] = {"caller_thread_id": "supervisor-native-host", "model": "gpt-6.1-sol",
        "reasoning_effort": "xhigh", "plugin_sha256": "a" * 64}
    write_json(endpoint_path, endpoint)
    supervisor_ref = ref(endpoint_path)
    host["roles"]["supervisor"]["endpoint_sha256"] = supervisor_ref["sha256"]
    write_json(host_path, host)
    packet["host_binding"] = ref(host_path)
    for leg in packet["legs"]:
        if leg["receiver_role"] != "supervisor":
            continue
        leg["endpoint"] = supervisor_ref
        if leg["commit_request"]:
            commit_path = Path(leg["commit_request"]["path"])
            commit = json.loads(commit_path.read_text())
            commit["start_evidence"]["endpoint_sha256"] = supervisor_ref["sha256"]
            write_json(commit_path, commit)
            leg["commit_request"] = ref(commit_path)
    endpoint["address"]["desktop"]["caller_thread_id"] = "registered-ow-session"
    packet["legs"][-1]["endpoint"] = ref(write_json(tmp_path / "ow-notification-endpoint.json", endpoint))
    write_json(packet_path, packet)
    return request


def test_native_ow_notification_keeps_receiver_but_uses_its_own_registered_caller(tmp_path):
    assert evaluate_run_readiness(_native_ow_request(tmp_path))["status"] == "READY"


@pytest.mark.parametrize("damage", ["supervisor-caller", "other-caller", "receiver", "model", "instance", "ow-state", "ow-session"])
def test_native_ow_caller_override_cannot_change_any_other_frozen_identity(tmp_path, damage):
    request = _native_ow_request(tmp_path)
    packet_path = Path(request["communication_rehearsal"])
    packet = json.loads(packet_path.read_text())
    reference = packet["legs"][-1]["endpoint"]
    endpoint_path = Path(reference["path"])
    endpoint = json.loads(endpoint_path.read_text())
    if damage in {"supervisor-caller", "other-caller"}:
        endpoint["address"]["desktop"]["caller_thread_id"] = "supervisor-native-host" if damage == "supervisor-caller" else "other-session"
    elif damage == "receiver": endpoint["address"]["thread_id"] = "other-supervisor"
    elif damage == "model": endpoint["address"]["desktop"]["model"] = "gpt-6-sol"
    elif damage == "instance": endpoint["role_instance_id"] = "other-supervisor"
    else:
        ow_path = Path(request["roles"][-1]["endpoint_path"])
        ow = json.loads(ow_path.read_text())
        if damage == "ow-state": ow["state"] = "retired"
        else: ow["address"]["thread_id"] = "other-ow-session"
        write_json(ow_path, ow)
    write_json(endpoint_path, endpoint)
    reference["sha256"] = hashlib.sha256(endpoint_path.read_bytes()).hexdigest()
    write_json(packet_path, packet)
    result = evaluate_run_readiness(request)
    assert result["status"] == "REPAIR_NEEDED"
    assert "COMMUNICATION_REHEARSAL_INVALID" in result["reason_codes"]


@pytest.mark.parametrize("current_join_matches", [True, False])
def test_historical_worker_activation_needs_live_exact_central_handoff_join(tmp_path, monkeypatch, current_join_matches):
    from slk_transport.role_host import RoleHost
    request = _request(tmp_path)
    packet_path = Path(request["communication_rehearsal"])
    packet = json.loads(packet_path.read_text())
    leg = packet["legs"][2]
    commit = json.loads(Path(leg["commit_request"]["path"]).read_text())
    result_path = Path(leg["commit_result"]["path"])
    write_json(result_path, {"status": "CHECKER_STARTED", "runtime_revision": 10, "token_sequence": commit["token_sequence"],
        "candidate_message_id": commit["message_id"], "checker_token_already_committed": False,
        "native_attempt_path": str(Path(leg["receiver_started"]["path"]).parent), "binding_sha256": packet["host_binding"]["sha256"],
        "source_message_id": "original-worker-message", "source_sha256": "f" * 64})
    leg["commit_result"]["sha256"] = hashlib.sha256(result_path.read_bytes()).hexdigest()
    write_json(packet_path, packet)
    monkeypatch.setattr(RoleHost, "projection", lambda self: {"contract_fixture_only": True})
    monkeypatch.setattr(RoleHost, "_committed_delivery", lambda self, projection, envelope, native: current_join_matches)
    result = evaluate_run_readiness(request)
    assert result["status"] == ("READY" if current_join_matches else "REPAIR_NEEDED")
