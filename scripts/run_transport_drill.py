#!/usr/bin/env python3
"""Run the disposable four-leg SLK cross-Agent transport drill."""

from __future__ import annotations

import json
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from pathlib import Path
from typing import Any, Mapping, Sequence

from slk_transport.adapters.codex import CodexAdapter
from slk_transport.adapters.dsh import DshAdapter
from slk_transport.adapters.ocrv import OcrvAdapter
from slk_transport.contracts import (
    ENDPOINT_SCHEMA,
    ENVELOPE_SCHEMA,
    ContractError,
    Endpoint,
    Envelope,
    canonical_json_sha256,
)
from slk_transport.dispatcher import dispatch_once


ADAPTERS = {
    "codex-app-server": CodexAdapter(),
    "ocrv-checker": OcrvAdapter(),
    "dsh-worker": DshAdapter(),
}


def _command(config: Mapping[str, object], field: str) -> list[str]:
    value = config.get(field)
    if not isinstance(value, list) or not value or not all(isinstance(item, str) and item for item in value):
        raise ValueError(f"{field} must be a non-empty string array")
    return list(value)


def _seconds(config: Mapping[str, object]) -> float:
    value = config.get("timeout_seconds")
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        raise ValueError("timeout_seconds must be positive")
    return float(value)


def _root(config: Mapping[str, object], field: str) -> Path:
    value = config.get(field)
    if not isinstance(value, str) or not Path(value).is_absolute():
        raise ValueError(f"{field} must be an absolute path")
    path = Path(value)
    path.mkdir(parents=True, exist_ok=True)
    return path.resolve()


def _endpoint(
    *,
    run_id: str,
    role: str,
    runtime: str,
    adapter: str,
    version: int,
    address: Mapping[str, object],
    state: str = "active",
) -> dict[str, object]:
    return {
        "schema_version": ENDPOINT_SCHEMA,
        "run_id": run_id,
        "role": role,
        "role_instance_id": f"{run_id}-{role}-001",
        "agent_runtime": runtime,
        "adapter": adapter,
        "host_id": "local",
        "endpoint_version": version,
        "state": state,
        "address": dict(address),
    }


def _envelope(
    *,
    token_sequence: int,
    run_id: str,
    sender: Endpoint,
    receiver: Endpoint,
    payload_type: str,
    payload: Mapping[str, object],
) -> dict[str, object]:
    return {
        "schema_version": ENVELOPE_SCHEMA,
        "message_id": str(uuid.uuid4()),
        "token_sequence": token_sequence,
        "run_id": run_id,
        "go_id": "GO-001",
        "cell_id": "CELL-001",
        "sender_role": sender.role,
        "sender_role_instance_id": sender.role_instance_id,
        "receiver_role": receiver.role,
        "receiver_role_instance_id": receiver.role_instance_id,
        "receiver_endpoint_version": receiver.endpoint_version,
        "payload_type": payload_type,
        "payload_sha256": canonical_json_sha256(payload),
        "payload": dict(payload),
    }


def _require_completed(result: object, leg: str) -> None:
    status = getattr(result, "status", None)
    if status != "completed":
        code = getattr(result, "error_code", None)
        raise RuntimeError(f"transport drill leg {leg} failed: {code}")


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise RuntimeError(f"drill evidence is not an object: {path}")
    return value


def _one_offline_run(config: Mapping[str, object], run_id: str) -> dict[str, Any]:
    evidence_root = _root(config, "evidence_root")
    workspace_root = _root(config, "workspace_root")
    timeout = _seconds(config)
    workspace = workspace_root / run_id
    repository = workspace / "repository"
    ocrv_runtime = workspace / "ocrv-runtime"
    dsh_runtime = workspace / "dsh-runtime"
    for path in (repository, ocrv_runtime, dsh_runtime):
        path.mkdir(parents=True, exist_ok=True)
    nonce = f"{run_id}-NONCE"

    supervisor = Endpoint.from_dict(
        _endpoint(
            run_id=run_id,
            role="supervisor",
            runtime="codex",
            adapter="codex-app-server",
            version=1,
            address={
                "command": _command(config, "codex_command"),
                "thread_id": f"thread-{run_id}",
                "cwd": str(repository),
                "startup_timeout_seconds": timeout,
                "turn_timeout_seconds": timeout,
            },
        )
    )
    checker = Endpoint.from_dict(
        _endpoint(
            run_id=run_id,
            role="checker",
            runtime="ocrv",
            adapter="ocrv-checker",
            version=1,
            address={
                "command": _command(config, "ocrv_command"),
                "runtime_root": str(ocrv_runtime),
                "timeout_seconds": timeout,
            },
        )
    )
    worker = Endpoint.from_dict(
        _endpoint(
            run_id=run_id,
            role="worker",
            runtime="dsh",
            adapter="dsh-worker",
            version=2,
            address={
                "command": _command(config, "dsh_command"),
                "instance_id": f"{run_id}-worker",
                "session_id": None,
                "runtime_root": str(dsh_runtime),
                "cwd": str(repository),
                "timeout_seconds": timeout,
            },
        )
    )

    initial_payload = {
        "worker_endpoint": asdict(worker),
        "worker_payload": {
            "probe_nonce": nonce,
            "task": "Complete the no-project-change transport probe and return the nonce.",
        },
    }
    initial = Envelope.from_dict(
        _envelope(
            token_sequence=1,
            run_id=run_id,
            sender=supervisor,
            receiver=checker,
            payload_type="CELL_DISPATCH",
            payload=initial_payload,
        )
    )
    first = dispatch_once(
        asdict(checker),
        asdict(initial),
        evidence_root,
        adapters=ADAPTERS,
    )
    _require_completed(first, "S-C")
    first_attempt = evidence_root / run_id / initial.message_id
    checker_result = _read_json(first_attempt / "checker-result.json")
    worker_endpoint = Endpoint.from_dict(checker_result["next_endpoint"])
    worker_envelope = Envelope.from_dict(checker_result["next_envelope"])

    retired_worker_raw = asdict(worker_endpoint)
    retired_worker_raw["endpoint_version"] = 1
    retired_worker_raw["state"] = "retired"
    retired_worker = Endpoint.from_dict(retired_worker_raw)
    retired_probe = Envelope.from_dict(
        _envelope(
            token_sequence=worker_envelope.token_sequence,
            run_id=run_id,
            sender=checker,
            receiver=retired_worker,
            payload_type="WORKER_TASK",
            payload={"probe_nonce": nonce, "task": "Retired endpoint rejection probe."},
        )
    )
    rejected = False
    try:
        dispatch_once(
            asdict(retired_worker),
            asdict(retired_probe),
            evidence_root,
            adapters=ADAPTERS,
        )
    except ContractError:
        rejected = True
    if not rejected:
        raise RuntimeError("retired Worker endpoint accepted a delivery")

    second = dispatch_once(
        asdict(worker_endpoint),
        asdict(worker_envelope),
        evidence_root,
        adapters=ADAPTERS,
    )
    _require_completed(second, "C-W")
    second_attempt = evidence_root / run_id / worker_envelope.message_id
    worker_result = _read_json(second_attempt / "worker-result.json")
    if worker_result.get("next_payload", {}).get("probe_nonce") != nonce:
        raise RuntimeError("Worker returned a different Run nonce")

    candidate_payload = {
        "repository": str(repository),
        "candidate": {"kind": "workspace"},
        "cell_goal": f"Verify the no-project-change probe for {nonce}.",
        "d1_criteria": [f"The result remains bound to {nonce}."],
        "evidence_files": [],
    }
    candidate = Envelope.from_dict(
        _envelope(
            token_sequence=worker_envelope.token_sequence + 1,
            run_id=run_id,
            sender=worker_endpoint,
            receiver=checker,
            payload_type="CANDIDATE_READY",
            payload=candidate_payload,
        )
    )
    third = dispatch_once(
        asdict(checker),
        asdict(candidate),
        evidence_root,
        adapters=ADAPTERS,
    )
    _require_completed(third, "W-C")
    if third.native_identity.get("verdict") != "PASS":
        raise RuntimeError("OCRV did not PASS the transport probe")

    final_payload = {
        "probe_nonce": nonce,
        "d1_verdict": third.native_identity["verdict"],
        "worker_native_identity": dict(second.native_identity),
        "checker_native_identity": dict(third.native_identity),
    }
    final = Envelope.from_dict(
        _envelope(
            token_sequence=candidate.token_sequence + 1,
            run_id=run_id,
            sender=checker,
            receiver=supervisor,
            payload_type="D1_RESULT",
            payload=final_payload,
        )
    )
    fourth = dispatch_once(
        asdict(supervisor),
        asdict(final),
        evidence_root,
        adapters=ADAPTERS,
    )
    _require_completed(fourth, "C-S")

    return {
        "legs": ["S-C", "C-W", "W-C", "C-S"],
        "probe_nonce": nonce,
        "final_token_sequence": final.token_sequence,
        "native_identities": {
            "worker": dict(second.native_identity),
            "checker": dict(third.native_identity),
            "supervisor": dict(fourth.native_identity),
        },
        "failed_delivery": {
            "rejected": rejected,
            "token_before": retired_probe.token_sequence,
            "token_after": worker_envelope.token_sequence,
        },
        "endpoint_rebound": {
            "retired_version_rejected": rejected,
            "active_version": worker_endpoint.endpoint_version,
            "active_version_completed": second.status == "completed",
        },
    }


def _find_crossovers(
    config: Mapping[str, object],
    run_ids: Sequence[str],
) -> list[dict[str, str]]:
    evidence_root = _root(config, "evidence_root")
    crossovers: list[dict[str, str]] = []
    for run_id in run_ids:
        run_root = evidence_root / run_id
        for path in run_root.rglob("*"):
            if not path.is_file():
                continue
            text = path.read_text(encoding="utf-8-sig", errors="replace")
            for other in run_ids:
                if other != run_id and f"{other}-NONCE" in text:
                    crossovers.append({"run_id": run_id, "other_run_id": other, "file": str(path)})
    return crossovers


def run_drill(
    config: Mapping[str, object],
    *,
    live: bool,
    run_ids: Sequence[str],
) -> dict[str, Any]:
    """Run two isolated transport chains and report exact native identities."""

    if not run_ids or len(set(run_ids)) != len(run_ids):
        raise ValueError("run_ids must be unique and non-empty")
    if live and "live_endpoints" not in config:
        raise ValueError("live drill requires explicit real runtime endpoints")
    if live:
        raise NotImplementedError("real runtime bootstrap is completed by the live acceptance Cell")
    with ThreadPoolExecutor(max_workers=len(run_ids)) as executor:
        futures = {
            run_id: executor.submit(_one_offline_run, config, run_id)
            for run_id in run_ids
        }
        summary = {run_id: future.result() for run_id, future in futures.items()}
    summary["crossovers"] = _find_crossovers(config, run_ids)
    return summary
