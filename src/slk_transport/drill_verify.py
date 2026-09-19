"""Independent verification for an SLK cross-Agent transport drill."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from .contracts import DeliveryResult, Endpoint, Envelope, parse_delivery


EXPECTED_LEGS = (
    ("supervisor", "checker", "CELL_DISPATCH", "S-C"),
    ("checker", "worker", "WORKER_TASK", "C-W"),
    ("worker", "checker", "CANDIDATE_READY", "W-C"),
    ("checker", "supervisor", "D1_RESULT", "C-S"),
)


class DrillVerificationError(RuntimeError):
    """The persisted drill evidence does not prove the required graph."""


def _read(path: Path) -> Mapping[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DrillVerificationError(f"unreadable drill evidence: {path}") from exc
    if not isinstance(value, dict):
        raise DrillVerificationError(f"drill evidence is not an object: {path}")
    return value


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise DrillVerificationError(f"missing {label}")
    return value


def _verify_run(run_root: Path) -> dict[str, Any]:
    attempts: list[tuple[Endpoint, Envelope, DeliveryResult, Path]] = []
    for attempt_root in run_root.iterdir():
        if not attempt_root.is_dir() or attempt_root.name.startswith("_"):
            continue
        endpoint_path = attempt_root / "endpoint.json"
        envelope_path = attempt_root / "envelope.json"
        if not endpoint_path.is_file() and not envelope_path.is_file():
            continue
        if not endpoint_path.is_file() or not envelope_path.is_file():
            raise DrillVerificationError(f"incomplete attempt identity: {attempt_root}")
        if (attempt_root / "failed.json").exists():
            raise DrillVerificationError(f"terminal failed attempt in accepted drill: {attempt_root}")
        completed_path = attempt_root / "completed.json"
        if not completed_path.is_file():
            raise DrillVerificationError(f"missing completed evidence: {attempt_root}")
        if not (attempt_root / "started.json").is_file():
            raise DrillVerificationError(f"missing started evidence: {attempt_root}")
        parsed = parse_delivery(_read(endpoint_path), _read(envelope_path))
        result = DeliveryResult.from_dict(_read(completed_path))
        if result.status != "completed":
            raise DrillVerificationError(f"non-completed terminal result: {attempt_root}")
        if result.message_id != parsed.envelope.message_id or result.run_id != parsed.envelope.run_id:
            raise DrillVerificationError(f"terminal identity mismatch: {attempt_root}")
        attempts.append((parsed.endpoint, parsed.envelope, result, attempt_root))
    if len(attempts) != 4:
        raise DrillVerificationError(f"Run {run_root.name} has {len(attempts)} completed legs instead of four")
    attempts.sort(key=lambda item: item[1].token_sequence)
    legs: list[str] = []
    for sequence, expected, item in zip(range(1, 5), EXPECTED_LEGS, attempts, strict=True):
        endpoint, envelope, result, _ = item
        sender, receiver, payload_type, label = expected
        if envelope.token_sequence != sequence:
            raise DrillVerificationError(f"Run {run_root.name} token sequence is not 1..4")
        if (envelope.sender_role, envelope.receiver_role, envelope.payload_type) != (
            sender,
            receiver,
            payload_type,
        ):
            raise DrillVerificationError(f"Run {run_root.name} leg {sequence} route mismatch")
        if endpoint.role != receiver or result.adapter != endpoint.adapter:
            raise DrillVerificationError(f"Run {run_root.name} leg {sequence} endpoint mismatch")
        legs.append(label)

    first_payload = attempts[0][1].payload
    worker_payload = first_payload.get("worker_payload")
    if not isinstance(worker_payload, Mapping):
        raise DrillVerificationError(f"Run {run_root.name} lacks the initial Worker payload")
    nonce = _text(worker_payload.get("probe_nonce"), "initial probe nonce")
    if attempts[1][1].payload.get("probe_nonce") != nonce:
        raise DrillVerificationError(f"Run {run_root.name} Worker envelope nonce mismatch")
    worker_result = _read(attempts[1][3] / "worker-result.json")
    next_payload = worker_result.get("next_payload")
    if not isinstance(next_payload, Mapping) or next_payload.get("probe_nonce") != nonce:
        raise DrillVerificationError(f"Run {run_root.name} Worker result nonce mismatch")
    if attempts[3][1].payload.get("probe_nonce") != nonce:
        raise DrillVerificationError(f"Run {run_root.name} Supervisor result nonce mismatch")

    worker_identity = attempts[1][2].native_identity
    checker_identity = attempts[2][2].native_identity
    supervisor_identity = attempts[3][2].native_identity
    if checker_identity.get("verdict") != "PASS":
        raise DrillVerificationError(f"Run {run_root.name} OCRV verdict is not PASS")
    identities = {
        "worker_instance_id": _text(worker_identity.get("instance_id"), "Worker instance identity"),
        "worker_session_id": _text(worker_identity.get("session_id"), "Worker session identity"),
        "checker_review_invocation_id": _text(
            checker_identity.get("review_invocation_id"), "Checker review identity"
        ),
        "checker_session_id": _text(checker_identity.get("session_id"), "Checker session identity"),
        "supervisor_thread_id": _text(supervisor_identity.get("thread_id"), "Supervisor thread identity"),
        "supervisor_turn_id": _text(supervisor_identity.get("turn_id"), "Supervisor turn identity"),
    }
    return {
        "legs": legs,
        "token_sequences": [item[1].token_sequence for item in attempts],
        "message_ids": [item[1].message_id for item in attempts],
        "probe_nonce": nonce,
        "native_identities": identities,
    }


def verify_drill(evidence_root: Path | str) -> dict[str, Any]:
    root = Path(evidence_root).resolve()
    if not root.is_dir():
        raise DrillVerificationError("evidence_root must be an existing directory")
    run_roots = sorted(
        path for path in root.iterdir() if path.is_dir() and not path.name.startswith(('.', '_'))
    )
    if len(run_roots) < 2:
        raise DrillVerificationError("accepted drill requires at least two simultaneous Runs")
    runs = {run_root.name: _verify_run(run_root) for run_root in run_roots}

    identity_fields = (
        "worker_instance_id",
        "worker_session_id",
        "checker_review_invocation_id",
        "checker_session_id",
        "supervisor_thread_id",
    )
    for field in identity_fields:
        values = [run["native_identities"][field] for run in runs.values()]
        if len(values) != len(set(values)):
            raise DrillVerificationError(f"native identity crossed Runs: {field}")
    nonces = {run_id: value["probe_nonce"] for run_id, value in runs.items()}
    if len(nonces) != len(set(nonces.values())):
        raise DrillVerificationError("probe nonce is not unique per Run")
    for run_root in run_roots:
        for path in run_root.rglob("*"):
            if not path.is_file():
                continue
            text = path.read_text(encoding="utf-8-sig", errors="replace")
            for other_run_id, other_nonce in nonces.items():
                if other_run_id != run_root.name and other_nonce in text:
                    raise DrillVerificationError(
                        f"cross-Run nonce in {run_root.name}: {path.relative_to(root)}"
                    )
    return {
        "status": "TRANSPORT_DRILL_PASS",
        "run_ids": sorted(runs),
        "runs": runs,
    }
