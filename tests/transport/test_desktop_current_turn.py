from __future__ import annotations

import copy
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from slk_transport.adapters.codex import CodexAdapter
from slk_transport.contracts import ContractError
from slk_transport.desktop_current_turn import (
    complete_desktop_current_turn,
    prepare_desktop_current_turn,
)
from slk_transport.dispatcher import dispatch_once
from slk_transport.recovery import retry_exact
from scripts.build_transport_zipapp import build_zipapp

from test_active_writer import delivery


FAKE_SERVER = Path(__file__).with_name("fake_app_server.py")
REPOSITORY = Path(__file__).resolve().parents[2]


def canonical_sha(value: object) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def unresolved_delivery(
    tmp_path: Path, *, with_exact_retry: bool = True
) -> tuple[dict[str, object], dict[str, object], Path, Path]:
    endpoint, envelope = delivery(tmp_path)
    endpoint["address"]["startup_timeout_seconds"] = 3
    endpoint["address"]["command"] = [
        sys.executable,
        str(FAKE_SERVER),
        "initialize-writer-conflict",
    ]
    attempts = tmp_path / "attempts"
    result = dispatch_once(
        endpoint,
        envelope,
        attempts,
        adapters={"codex-app-server": CodexAdapter()},
    )
    assert result.error_code == "CODEX_ACTIVE_WRITER_UNRESOLVED"
    original = attempts / str(envelope["run_id"]) / str(envelope["message_id"])
    assert not (original / "started.json").exists()
    assert not (original / "active-writer.json").exists()
    if with_exact_retry:
        retry = retry_exact(
            attempts,
            endpoint,
            envelope,
            adapters={"codex-app-server": CodexAdapter()},
        )
        assert retry["status"] == "SUPERVISOR_DECISION_REQUIRED"
        assert retry["reason"] == "EXACT_RETRY_EXHAUSTED"
    return endpoint, envelope, attempts, original


def rpc_timeout_delivery(
    tmp_path: Path, mode: str, *, legacy_full_read: bool = False
) -> tuple[dict[str, object], dict[str, object], Path, Path]:
    endpoint, envelope = delivery(tmp_path)
    endpoint["address"]["command"] = [sys.executable, str(FAKE_SERVER), mode]
    endpoint["address"]["startup_timeout_seconds"] = 1
    attempts = tmp_path / "attempts"
    result = dispatch_once(
        endpoint,
        envelope,
        attempts,
        adapters={"codex-app-server": CodexAdapter()},
    )
    assert result.error_code == "CODEX_RPC_TIMEOUT"
    retry = retry_exact(
        attempts,
        endpoint,
        envelope,
        adapters={"codex-app-server": CodexAdapter()},
    )
    assert retry["status"] == "SUPERVISOR_DECISION_REQUIRED"
    assert retry["reason"] == "EXACT_RETRY_EXHAUSTED"
    assert retry["result"]["error_code"] == "CODEX_RPC_TIMEOUT"
    original = attempts / str(envelope["run_id"]) / str(envelope["message_id"])
    if legacy_full_read:
        roots = [
            original,
            original
            / "recovery"
            / "exact-1"
            / str(envelope["run_id"])
            / str(envelope["message_id"]),
        ]
        for root in roots:
            transcript = root / "native.stdout.txt"
            text = transcript.read_text(encoding="utf-8")
            assert '"includeTurns":false' in text
            transcript.write_text(
                text.replace('"includeTurns":false', '"includeTurns":true'),
                encoding="utf-8",
            )
    return endpoint, envelope, attempts, original


def host_receipt(request: dict[str, object]) -> dict[str, object]:
    turn_id = "turn-desktop-active"
    return {
        "schema_version": "slk.transport-desktop-current-turn-host-receipt/v1",
        "request_sha256": canonical_sha(request),
        "host_thread_id": "thread-bridge-host",
        "host_turn_id": "turn-bridge-host",
        "host_session_id": "thread-bridge-host",
        "target_thread_id": request["target_thread_id"],
        "before": {
            "thread_status": "active",
            "turn_id": turn_id,
            "turn_status": "inProgress",
        },
        "after": {
            "thread_status": "active",
            "turn_id": turn_id,
            "turn_status": "inProgress",
            "platform_item_id": "fco-desktop-recovery",
            "item_type": "functionCallOutput",
            "item_name": "send_message_to_thread",
            "item_namespace": "codex_app",
            "message_sha256": request["prompt_sha256"],
        },
        "status": "PLATFORM_READBACK_CONFIRMED",
    }


def desktop_environment() -> dict[str, str]:
    return {
        "CODEX_INTERNAL_ORIGINATOR_OVERRIDE": "Codex Desktop",
        "CODEX_THREAD_ID": "thread-bridge-host",
        "CODEX_SESSION_ID": "thread-bridge-host",
    }


def native_platform_record(tmp_path, monkeypatch, request, receipt):
    """Real native record shape, not a second high-level receipt claiming success."""
    home = tmp_path / "codex-home"
    monkeypatch.setenv("CODEX_HOME", str(home))
    path = home / "sessions/2026/10/09" / f"rollout-{request['target_thread_id']}.jsonl"
    path.parent.mkdir(parents=True)
    import html
    rows = [
        {"type": "session_meta", "payload": {"id": request["target_thread_id"], "originator": "Codex Desktop"}},
        {"type": "response_item", "payload": {
            "type": "function_call_output", "id": receipt["after"]["platform_item_id"],
            "name": "send_message_to_thread", "namespace": "codex_app",
            "output": "<codex_delegation><source_thread_id>thread-bridge-host</source_thread_id><input>"
                + html.escape(request["prompt"]) + "</input></codex_delegation>",
            "internal_chat_message_metadata_passthrough": {"turn_id": receipt["after"]["turn_id"]},
        }},
    ]
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
    return path


def test_current_turn_recovery_closes_original_temporal_ack_without_canonical_backfill(tmp_path, monkeypatch):
    from slk_transport import worker_completion as wc
    from test_temporal_handoff_bridge import temporal_binding
    endpoint, envelope, attempts, original = unresolved_delivery(tmp_path)
    request = prepare_desktop_current_turn(attempts, endpoint, envelope)
    receipt = host_receipt(request)
    native_platform_record(tmp_path, monkeypatch, request, receipt)
    complete_desktop_current_turn(attempts, endpoint, envelope, receipt, environment=desktop_environment())
    failed_before = (original / "failed.json").read_bytes()
    temporal_request = {
        "operation_id": "original-operation", "run_id": envelope["run_id"], "cell_id": envelope["cell_id"],
        "attempt": 2, "message_id": envelope["message_id"],
        "sender_role_instance_id": envelope["sender_role_instance_id"],
        "receiver_role_instance_id": envelope["receiver_role_instance_id"],
        "payload_sha256": envelope["payload_sha256"], "source_runtime_revision": 31,
    }
    path = tmp_path / "temporal-request.json"
    path.write_text(json.dumps(temporal_request), encoding="utf-8")
    calls = []
    def client(_command, arguments, **_kwargs):
        calls.append(arguments[0])
        ack = json.loads(Path(arguments[arguments.index("--request") + 1]).read_text())
        assert ack["message_id"] == envelope["message_id"]
        assert ack["payload_sha256"] == envelope["payload_sha256"]
        assert ack["started_receipt_sha256"] == hashlib.sha256(
            (original / "recovery/desktop-current-turn/start-evidence.json").read_bytes()).hexdigest()
        return {"schema_version": "slk.temporal-delivery-update-result/v1", "operation": "native_started",
                "status": "DELIVERY_ACKNOWLEDGED", "run_id": envelope["run_id"],
                "operation_id": "original-operation", "message_id": envelope["message_id"]}
    monkeypatch.setattr(wc, "_run_json_command", client)
    binding = temporal_binding(tmp_path, attempts)
    for _ in range(2):
        assert wc.acknowledge_temporal_delivery(binding, tmp_path / "ack", endpoint, envelope,
            request_path=path, request_sha256=wc._sha256(path), attempt=2) == original
    assert calls == ["native-started"]
    assert not (original / "started.json").exists()
    assert (original / "failed.json").read_bytes() == failed_before


@pytest.mark.parametrize("mutation", ["wrong-native-message", "wrong-native-turn", "wrong-recovery-parent"])
def test_recovery_start_resolver_rejects_forged_or_mismatched_platform_lineage(tmp_path, monkeypatch, mutation):
    from slk_transport.desktop_current_turn import resolve_delivery_start
    endpoint, envelope, attempts, original = unresolved_delivery(tmp_path)
    request = prepare_desktop_current_turn(attempts, endpoint, envelope)
    receipt = host_receipt(request)
    native_path = native_platform_record(tmp_path, monkeypatch, request, receipt)
    complete_desktop_current_turn(attempts, endpoint, envelope, receipt, environment=desktop_environment())
    if mutation == "wrong-recovery-parent":
        path = original / "recovery/desktop-current-turn/recovery.json"
        value = json.loads(path.read_text())
        value["recovery_of_message_id"] = "another-original-message"
        path.write_text(json.dumps(value), encoding="utf-8")
    else:
        rows = [json.loads(line) for line in native_path.read_text().splitlines()]
        if mutation == "wrong-native-turn":
            rows[1]["payload"]["internal_chat_message_metadata_passthrough"]["turn_id"] = "another-turn"
        else:
            rows[1]["payload"]["output"] = "<input>unrelated message</input>"
        native_path.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")
    with pytest.raises((ContractError, ValueError)):
        resolve_delivery_start(original, endpoint, envelope)
    assert not (original / "started.json").exists()


def test_desktop_owned_writer_recovers_original_unresolved_handoff_without_forging_start(
    tmp_path: Path,
) -> None:
    endpoint, envelope, attempts, original = unresolved_delivery(tmp_path)
    failed_before = (original / "failed.json").read_bytes()

    request = prepare_desktop_current_turn(attempts, endpoint, envelope)
    recovered = complete_desktop_current_turn(
        attempts,
        endpoint,
        envelope,
        host_receipt(request),
        environment=desktop_environment(),
    )

    assert recovered["status"] == "started"
    assert recovered["recovery_of_message_id"] == envelope["message_id"]
    assert recovered["recovery_message_id"] != envelope["message_id"]
    assert recovered["thread_id"] == endpoint["address"]["thread_id"]
    assert recovered["turn_id"] == "turn-desktop-active"
    assert recovered["payload_sha256"] == envelope["payload_sha256"]
    assert (original / "failed.json").read_bytes() == failed_before
    recovery_root = original / "recovery" / "desktop-current-turn"
    assert (recovery_root / "host-receipt.json").is_file()
    assert (recovery_root / "recovery.json").is_file()
    started = json.loads((recovery_root / "started.json").read_text(encoding="utf-8"))
    assert started["message_id"] == recovered["recovery_message_id"]
    assert started["request_sha256"] == envelope["payload_sha256"]
    assert started["native_request_sha256"] == request["prompt_sha256"]
    assert started["native_task"]["kind"] == "codex-desktop-turn"

    assert prepare_desktop_current_turn(attempts, endpoint, envelope) == request
    assert (
        complete_desktop_current_turn(
            attempts,
            endpoint,
            envelope,
            host_receipt(request),
            environment=desktop_environment(),
        )
        == recovered
    )


def test_desktop_bridge_requires_the_exhausted_exact_retry(tmp_path: Path) -> None:
    endpoint, envelope, attempts, original = unresolved_delivery(
        tmp_path, with_exact_retry=False
    )

    with pytest.raises(ContractError, match="exact retry"):
        prepare_desktop_current_turn(attempts, endpoint, envelope)

    assert not (original / "recovery" / "desktop-current-turn").exists()


@pytest.mark.parametrize("legacy_full_read", [False, True])
def test_desktop_bridge_accepts_only_exact_metadata_read_timeout(
    tmp_path: Path, legacy_full_read: bool
) -> None:
    endpoint, envelope, attempts, original = rpc_timeout_delivery(
        tmp_path, "metadata-rpc-timeout", legacy_full_read=legacy_full_read
    )
    failed_before = (original / "failed.json").read_bytes()

    request = prepare_desktop_current_turn(attempts, endpoint, envelope)

    assert request["status"] == "PREPARED"
    assert request["target_thread_id"] == endpoint["address"]["thread_id"]
    assert (original / "failed.json").read_bytes() == failed_before


@pytest.mark.parametrize("mode", ["initialize-rpc-timeout", "turn-start-rpc-timeout"])
def test_desktop_bridge_rejects_rpc_timeout_outside_metadata_read(
    tmp_path: Path, mode: str
) -> None:
    endpoint, envelope, attempts, original = rpc_timeout_delivery(tmp_path, mode)

    with pytest.raises(ContractError, match="metadata"):
        prepare_desktop_current_turn(attempts, endpoint, envelope)

    assert not (original / "recovery" / "desktop-current-turn").exists()


@pytest.mark.parametrize(
    ("mutation", "match"),
    [
        (lambda value: value.update(request_sha256="0" * 64), "request"),
        (lambda value: value.update(target_thread_id="wrong-thread"), "thread"),
        (lambda value: value["after"].update(turn_id="wrong-turn"), "turn"),
        (lambda value: value["after"].update(message_sha256="0" * 64), "message"),
        (lambda value: value["after"].update(item_name="ordinary_message"), "platform"),
    ],
)
def test_desktop_bridge_rejects_mismatched_platform_evidence_without_start(
    tmp_path: Path, mutation, match: str
) -> None:
    endpoint, envelope, attempts, original = unresolved_delivery(tmp_path)
    request = prepare_desktop_current_turn(attempts, endpoint, envelope)
    receipt = host_receipt(request)
    mutation(receipt)

    with pytest.raises(ContractError, match=match):
        complete_desktop_current_turn(
            attempts,
            endpoint,
            envelope,
            receipt,
            environment=desktop_environment(),
        )

    assert not (original / "recovery" / "desktop-current-turn" / "started.json").exists()


def test_desktop_bridge_rejects_changed_delivery_and_non_desktop_host(tmp_path: Path) -> None:
    endpoint, envelope, attempts, original = unresolved_delivery(tmp_path)
    request = prepare_desktop_current_turn(attempts, endpoint, envelope)

    changed = copy.deepcopy(envelope)
    changed["payload"]["expected_result"] = "changed"
    changed["payload_sha256"] = canonical_sha(changed["payload"])
    with pytest.raises(ContractError, match="identity"):
        complete_desktop_current_turn(
            attempts,
            endpoint,
            changed,
            host_receipt(request),
            environment=desktop_environment(),
        )

    environment = desktop_environment()
    environment.pop("CODEX_INTERNAL_ORIGINATOR_OVERRIDE")
    with pytest.raises(ContractError, match="Desktop host"):
        complete_desktop_current_turn(
            attempts,
            endpoint,
            envelope,
            host_receipt(request),
            environment=environment,
        )
    assert not (original / "recovery" / "desktop-current-turn" / "started.json").exists()


def test_zipapp_exposes_prepare_and_complete_desktop_bridge(tmp_path: Path) -> None:
    endpoint, envelope, attempts, original = unresolved_delivery(tmp_path)
    endpoint_path = tmp_path / "endpoint.json"
    envelope_path = tmp_path / "envelope.json"
    endpoint_path.write_text(json.dumps(endpoint), encoding="utf-8")
    envelope_path.write_text(json.dumps(envelope), encoding="utf-8")
    artifact = build_zipapp(tmp_path / "slk-transport.pyz")

    prepared = subprocess.run(
        [
            sys.executable,
            str(artifact),
            "prepare-desktop-current-turn",
            "--endpoint",
            str(endpoint_path),
            "--envelope",
            str(envelope_path),
            "--attempt-root",
            str(attempts),
        ],
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
    )
    assert prepared.returncode == 0, prepared.stderr
    request = json.loads(prepared.stdout)
    receipt_path = tmp_path / "host-receipt.json"
    receipt_path.write_text(json.dumps(host_receipt(request)), encoding="utf-8")
    environment = os.environ.copy()
    environment.update(desktop_environment())

    completed = subprocess.run(
        [
            sys.executable,
            str(artifact),
            "complete-desktop-current-turn",
            "--endpoint",
            str(endpoint_path),
            "--envelope",
            str(envelope_path),
            "--attempt-root",
            str(attempts),
            "--host-receipt",
            str(receipt_path),
        ],
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
        env=environment,
    )
    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout)["status"] == "started"
    assert (original / "recovery" / "desktop-current-turn" / "started.json").is_file()


def test_desktop_current_turn_contract_schema_is_closed() -> None:
    schema = json.loads(
        (
            REPOSITORY
            / "docs"
            / "contracts"
            / "slk-desktop-current-turn-recovery.schema.json"
        ).read_text(encoding="utf-8")
    )
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert set(schema["$defs"]) == {"request", "host_receipt", "recovery", "started"}
    for definition in schema["$defs"].values():
        assert definition["additionalProperties"] is False
