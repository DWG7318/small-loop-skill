#!/usr/bin/env python3
"""Run the disposable four-leg SLK cross-Agent transport drill."""

from __future__ import annotations

import json
import subprocess
import sys
import time
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
    DeliveryResult,
    Endpoint,
    Envelope,
    canonical_json_sha256,
)
from slk_transport.dispatcher import dispatch_once
from slk_transport.jsonrpc import JsonRpcProcess


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


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, sort_keys=True, indent=2)
        stream.write("\n")


def _save_rpc_evidence(root: Path, name: str, client: JsonRpcProcess) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / f"{name}.stdout.txt").write_text(
        "\n".join(client.transcript) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    (root / f"{name}.stderr.txt").write_text(
        "\n".join(client.stderr_lines) + ("\n" if client.stderr_lines else ""),
        encoding="utf-8",
        newline="\n",
    )


def _initialize_disposable_repository(repository: Path, run_id: str) -> str:
    (repository / "README.md").write_text(
        f"# Disposable SLK transport drill\n\nRun: `{run_id}`\n",
        encoding="utf-8",
        newline="\n",
    )
    commands = (
        ["git", "init", "-b", "main"],
        ["git", "config", "user.name", "SLK Transport Drill"],
        ["git", "config", "user.email", "slk-transport@example.invalid"],
        ["git", "add", "README.md"],
        ["git", "commit", "-m", "chore: initialize transport drill"],
    )
    for command in commands:
        completed = subprocess.run(
            command,
            cwd=repository,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            check=False,
        )
        if completed.returncode != 0:
            raise RuntimeError(f"disposable repository command failed: {' '.join(command)}")
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repository,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=True,
    ).stdout.strip()
    return head


def _create_supervisor_thread(
    config: Mapping[str, object],
    run_id: str,
    repository: Path,
    evidence_root: Path,
) -> tuple[str, JsonRpcProcess]:
    timeout = _seconds(config)
    model = config.get("codex_model")
    effort = config.get("codex_effort")
    if not isinstance(model, str) or not model or not isinstance(effort, str) or not effort:
        raise ValueError("live drill requires explicit codex_model and codex_effort")
    client = JsonRpcProcess(_command(config, "codex_command"), repository)
    try:
        client.request(
            1,
            "initialize",
            {"clientInfo": {"name": "slk_transport_drill", "title": "SLK Transport Drill", "version": "4.0.0"}},
            timeout,
        )
        client.notify("initialized", {})
        response = client.request(
            2,
            "thread/start",
            {
                "cwd": str(repository),
                "model": model,
                "approvalPolicy": "never",
                "sandbox": "danger-full-access",
                "baseInstructions": (
                    f"You are the disposable SLK Supervisor Agent for {run_id}. "
                    "Perform only the exact transport-drill assignment sent in the next turn."
                ),
            },
            timeout,
        )
        thread = response.get("thread")
        thread_id = thread.get("id") if isinstance(thread, Mapping) else None
        if not isinstance(thread_id, str) or not thread_id:
            raise RuntimeError("Codex thread/start returned no exact thread identity")
        return thread_id, client
    except Exception:
        client.close()
        _save_rpc_evidence(evidence_root / run_id / "_supervisor", "thread-start", client)
        raise


def _supervisor_starts_first_send(
    config: Mapping[str, object],
    run_id: str,
    thread_id: str,
    repository: Path,
    endpoint_path: Path,
    envelope_path: Path,
    evidence_root: Path,
    message_id: str,
    client: JsonRpcProcess | None = None,
) -> DeliveryResult:
    artifact_value = config.get("transport_artifact")
    if not isinstance(artifact_value, str):
        raise ValueError("live drill requires transport_artifact")
    artifact = Path(artifact_value).resolve()
    if not artifact.is_file():
        raise ValueError("transport_artifact must be an existing file")
    command = [
        sys.executable,
        str(artifact),
        "send",
        "--endpoint",
        str(endpoint_path),
        "--envelope",
        str(envelope_path),
        "--attempt-root",
        str(evidence_root),
        "--startup-timeout-seconds",
        str(_seconds(config)),
    ]
    prompt = (
        f"Start the real first SLK transport handoff for {run_id}. Execute exactly the JSON-array "
        "command below with the shell now. Do not merely quote it, explain it, or substitute another "
        "command. Make no project changes. Report the command exit status after it returns.\n"
        f"<slk-supervisor-command>{json.dumps(command, ensure_ascii=False)}</slk-supervisor-command>"
    )
    timeout = _seconds(config)
    existing_client = client is not None
    if client is None:
        client = JsonRpcProcess(_command(config, "codex_command"), repository)
    try:
        request_id = 3
        if not existing_client:
            client.request(
                1,
                "initialize",
                {"clientInfo": {"name": "slk_transport_drill", "title": "SLK Transport Drill", "version": "4.0.0"}},
                timeout,
            )
            client.notify("initialized", {})
            resumed = client.request(2, "thread/resume", {"threadId": thread_id, "cwd": str(repository)}, timeout)
            thread = resumed.get("thread")
            if not isinstance(thread, Mapping) or thread.get("id") != thread_id:
                raise RuntimeError("Supervisor thread resume identity mismatch")
            read = client.request(3, "thread/read", {"threadId": thread_id, "includeTurns": False}, timeout)
            read_thread = read.get("thread")
            status = read_thread.get("status") if isinstance(read_thread, Mapping) else None
            if not isinstance(status, Mapping) or status.get("type") != "idle":
                raise RuntimeError("Supervisor thread is not idle before first send")
            request_id = 4
        notification_start = len(client.messages)
        started_response = client.request(
            request_id,
            "turn/start",
            {
                "threadId": thread_id,
                "input": [{"type": "text", "text": prompt}],
                "cwd": str(repository),
                "model": config["codex_model"],
                "effort": config["codex_effort"],
                "approvalPolicy": "never",
                "sandboxPolicy": {"type": "dangerFullAccess"},
                "clientUserMessageId": str(uuid.uuid4()),
                "turnTrigger": "slk-transport-drill",
            },
            timeout,
        )
        turn = started_response.get("turn")
        turn_id = turn.get("id") if isinstance(turn, Mapping) else None
        if not isinstance(turn_id, str) or not turn_id:
            raise RuntimeError("Supervisor turn/start returned no turn identity")
        client.wait_for(
            "turn/started",
            lambda params: params.get("threadId") == thread_id
            and isinstance(params.get("turn"), Mapping)
            and params["turn"].get("id") == turn_id,
            timeout,
            after=notification_start,
        )
        completed = client.wait_for(
            "turn/completed",
            lambda params: params.get("threadId") == thread_id
            and isinstance(params.get("turn"), Mapping)
            and params["turn"].get("id") == turn_id,
            timeout,
            after=notification_start,
        )
        terminal = completed["turn"]
        if terminal.get("status") != "completed":
            raise RuntimeError(f"Supervisor first-send turn ended with {terminal.get('status')}")
    finally:
        client.close()
        _save_rpc_evidence(
            evidence_root / run_id / "_supervisor",
            "thread-start-and-first-send" if existing_client else "first-send",
            client,
        )
    attempt = evidence_root / run_id / message_id
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        completed_path = attempt / "completed.json"
        failed_path = attempt / "failed.json"
        if completed_path.is_file():
            return DeliveryResult.from_dict(_read_json(completed_path))
        if failed_path.is_file():
            result = DeliveryResult.from_dict(_read_json(failed_path))
            raise RuntimeError(f"Supervisor first send failed: {result.error_code}")
        time.sleep(0.05)
    raise RuntimeError("Supervisor turn completed without terminal first-send evidence")


def _one_run(config: Mapping[str, object], run_id: str, live: bool) -> dict[str, Any]:
    evidence_root = _root(config, "evidence_root")
    workspace_root = _root(config, "workspace_root")
    timeout = _seconds(config)
    workspace = workspace_root / run_id
    repository = workspace / "repository"
    ocrv_runtime = (
        Path(str(config["ocrv_runtime_root"])).resolve()
        if live and "ocrv_runtime_root" in config
        else workspace / "ocrv-runtime"
    )
    dsh_runtime = (
        Path(str(config["dsh_runtime_root"])).resolve()
        if live and "dsh_runtime_root" in config
        else workspace / "dsh-runtime"
    )
    for path in (repository, ocrv_runtime, dsh_runtime):
        path.mkdir(parents=True, exist_ok=True)
    nonce = f"{run_id}-NONCE"
    base_commit = _initialize_disposable_repository(repository, run_id) if live else None

    supervisor_client: JsonRpcProcess | None = None
    if live:
        thread_id, supervisor_client = _create_supervisor_thread(
            config, run_id, repository, evidence_root
        )
    else:
        thread_id = f"thread-{run_id}"
    supervisor = Endpoint.from_dict(
        _endpoint(
            run_id=run_id,
            role="supervisor",
            runtime="codex",
            adapter="codex-app-server",
            version=1,
            address={
                "command": _command(config, "codex_command"),
                "thread_id": thread_id,
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

    worker_task = (
        "This is a disposable Git repository. Create transport_probe.py as UTF-8 with exactly "
        f"PROBE_NONCE = \"{nonce}\" followed by one newline. Commit only that file with message "
        f"'test: record {nonce}'. In the required Worker result, use the exact new HEAD as a commit "
        f"candidate and set next_payload to exactly {{\"probe_nonce\":\"{nonce}\"}}."
        if live
        else "Complete the no-project-change transport probe and return the nonce."
    )
    initial_payload = {
        "worker_endpoint": asdict(worker),
        "worker_payload": {
            "probe_nonce": nonce,
            "task": worker_task,
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
    if live:
        input_root = evidence_root / run_id / "_inputs"
        endpoint_path = input_root / "checker-endpoint.json"
        envelope_path = input_root / "initial-envelope.json"
        _write_json(endpoint_path, asdict(checker))
        _write_json(envelope_path, asdict(initial))
        first = _supervisor_starts_first_send(
            config,
            run_id,
            thread_id,
            repository,
            endpoint_path,
            envelope_path,
            evidence_root,
            initial.message_id,
            supervisor_client,
        )
    else:
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

    candidate_value = worker_result["candidate"] if live else {"kind": "workspace"}
    candidate_payload = {
        "repository": str(repository),
        "candidate": candidate_value,
        "cell_goal": f"Verify the no-project-change probe for {nonce}.",
        "d1_criteria": [
            "The candidate adds only transport_probe.py to the disposable repository.",
            f"PROBE_NONCE is exactly {nonce} and does not reference another Run.",
        ],
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
        "supervisor_started_first_send": live,
        "disposable_base_commit": base_commit,
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
    with ThreadPoolExecutor(max_workers=len(run_ids)) as executor:
        futures = {
            run_id: executor.submit(_one_run, config, run_id, live)
            for run_id in run_ids
        }
        summary = {run_id: future.result() for run_id, future in futures.items()}
    summary["crossovers"] = _find_crossovers(config, run_ids)
    return summary
