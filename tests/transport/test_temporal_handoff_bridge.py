from __future__ import annotations

from dataclasses import asdict
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import sys
import threading

import pytest

from slk_transport.adapters.ocrv import OcrvAdapter
from slk_transport.contracts import ContractError, DeliveryResult, Envelope
from slk_transport.dispatcher import dispatch_once
from slk_transport.evidence import AttemptStore
from slk_transport.native_activity import make_native_start
from slk_transport.role_host import RoleHost
from slk_transport import worker_completion as wc

from test_ocrv_adapter import candidate_envelope, checker_endpoint
from test_role_host import host_boundary, prepared_host
from test_worker_completion import write_json
from test_contracts import endpoint_value, envelope_value


def temporal_identity(tmp_path: Path, run_id: str = "RUN-A") -> dict[str, str]:
    return {
        "schema_version": "slk.temporal-workflow-identity/v1",
        "run_id": run_id,
        "address": "127.0.0.1:7233",
        "task_queue": "slk-test",
        "start_workflow_id": f"slk-start-{run_id}",
        "start_run_id": "11111111-1111-4111-8111-111111111111",
        "run_workflow_id": f"slk-run-{run_id}",
        "run_run_id": "22222222-2222-4222-8222-222222222222",
        "startup_fingerprint": "a" * 64,
    }


def temporal_binding(tmp_path: Path, attempt_root: Path) -> dict[str, object]:
    attempt_root.mkdir(parents=True, exist_ok=True)
    identity = write_json(tmp_path / "temporal-workflow-identity.json", temporal_identity(tmp_path))
    return {
        "client_command": [sys.executable, "-m", "slk_temporal.delivery_client"],
        "workflow_identity_path": str(identity.resolve()),
        "workflow_identity_sha256": hashlib.sha256(identity.read_bytes()).hexdigest(),
        "attempt_root": str(attempt_root.resolve()),
    }


def test_dispatcher_continues_one_exact_temporal_prestage_into_real_native_v2(tmp_path: Path) -> None:
    endpoint = checker_endpoint(tmp_path)
    envelope = candidate_envelope(tmp_path)
    root = tmp_path / "attempts"
    attempt = AttemptStore(root).create(envelope)
    write_json(attempt.root / "endpoint.json", asdict(endpoint))
    write_json(attempt.root / "envelope.json", asdict(envelope))

    result = dispatch_once(asdict(endpoint), asdict(envelope), root, adapters={"ocrv-checker": OcrvAdapter()})

    assert result.status == "completed"
    started = wc._read_object(attempt.root / "started.json", "native start")
    assert started["schema_version"] == "slk.native-start/v2"
    assert started["message_id"] == envelope.message_id
    assert dispatch_once(asdict(endpoint), asdict(envelope), root,
                         adapters={"ocrv-checker": OcrvAdapter()}) == result


def test_atomic_accepted_claim_allows_only_one_native_adapter_for_competing_calls(tmp_path: Path) -> None:
    endpoint = checker_endpoint(tmp_path)
    envelope = candidate_envelope(tmp_path)
    root = tmp_path / "attempts"
    attempt = AttemptStore(root).create(envelope)
    write_json(attempt.root / "endpoint.json", asdict(endpoint))
    write_json(attempt.root / "envelope.json", asdict(envelope))
    entered, release = threading.Event(), threading.Event()
    calls = 0

    class CountingAdapter:
        def validate_address(self, _endpoint):
            return None

        def deliver(self, actual_endpoint, actual_envelope, actual_attempt):
            nonlocal calls
            calls += 1
            entered.set()
            assert release.wait(5)
            write_json(actual_attempt.root / "started.json", make_native_start(
                adapter=actual_endpoint.adapter, run_id=actual_envelope.run_id,
                cell_id=actual_envelope.cell_id, message_id=actual_envelope.message_id,
                request_sha256=actual_envelope.payload_sha256, native_request_sha256="f" * 64,
                native_task_kind="claim-test", native_task_id="only-one",
                native_task_status="RUNNING", pid=os.getpid()))
            return DeliveryResult(schema_version="slk.transport-result/v1",
                message_id=actual_envelope.message_id, run_id=actual_envelope.run_id,
                adapter=actual_endpoint.adapter, status="completed", native_identity={},
                error_code=None, evidence=())

    adapter = CountingAdapter()
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(dispatch_once, asdict(endpoint), asdict(envelope), root,
                            adapters={"ocrv-checker": adapter})
        assert entered.wait(5)
        second = pool.submit(dispatch_once, asdict(endpoint), asdict(envelope), root,
                             adapters={"ocrv-checker": adapter})
        with pytest.raises(Exception):
            second.result(timeout=5)
        release.set()
        assert first.result(timeout=5).status == "completed"
    assert calls == 1


def test_accepted_without_native_start_is_fail_closed_and_not_redispatched(tmp_path: Path) -> None:
    endpoint = checker_endpoint(tmp_path)
    envelope = candidate_envelope(tmp_path)
    root = tmp_path / "attempts"
    attempt = AttemptStore(root).create(envelope)
    write_json(attempt.root / "endpoint.json", asdict(endpoint))
    write_json(attempt.root / "envelope.json", asdict(envelope))
    write_json(attempt.root / "accepted.json", {
        "message_id": envelope.message_id, "run_id": envelope.run_id, "status": "accepted",
    })

    class ForbiddenAdapter:
        def validate_address(self, _endpoint):
            return None

        def deliver(self, *_args):
            pytest.fail("accepted interrupted attempt must not launch again")

    with pytest.raises(ContractError, match="without terminal evidence"):
        dispatch_once(asdict(endpoint), asdict(envelope), root,
                      adapters={"ocrv-checker": ForbiddenAdapter()})


@pytest.mark.parametrize("mode", ["new", "delivered", "delivered_identity_drift"])
def test_temporal_host_is_original_sender_but_never_calls_direct_transport(tmp_path: Path, monkeypatch, mode) -> None:
    host, source, envelope = prepared_host(tmp_path)
    canonical = tmp_path / "canonical-attempts"
    binding = {**host.binding, "schema_version": "slk.role-host/v2",
               "temporal": temporal_binding(tmp_path, canonical)}
    host = RoleHost(binding, "b" * 64)
    projection = host_boundary(host, envelope)
    monkeypatch.setattr(host, "projection", lambda: projection)
    monkeypatch.setattr(wc, "unprotect_dpapi_hex", lambda _p: "sealed-test-secret")
    calls: list[tuple[str, str]] = []
    attempt = canonical / envelope.run_id / envelope.message_id
    original_start = None
    if mode != "new":
        endpoint = host.endpoint(envelope.receiver_role)
        write_json(attempt / "endpoint.json", {**endpoint, **({"version": 999} if mode.endswith("drift") else {})})
        write_json(attempt / "envelope.json", asdict(envelope))
        write_json(attempt / "started.json", make_native_start(
            adapter=endpoint["adapter"], run_id=envelope.run_id, cell_id=envelope.cell_id,
            message_id=envelope.message_id, request_sha256=envelope.payload_sha256,
            native_request_sha256="c" * 64, native_task_kind="test-session",
            native_task_id="native-one", native_task_status="RUNNING", pid=os.getpid()))
        original_start = (attempt / "started.json").read_bytes()

    def command(command, arguments, **_kwargs):
        calls.append((str(command[0]), arguments[0]))
        if arguments[0] == "authenticate-role":
            return {"status": "authenticated", "run_id": envelope.run_id, "role": envelope.sender_role,
                    "role_instance_id": envelope.sender_role_instance_id, "runtime_revision": 7}
        if arguments[0] == "request-delivery":
            attempt = canonical / envelope.run_id / envelope.message_id
            endpoint = host.endpoint(envelope.receiver_role)
            if mode == "new":
                write_json(attempt / "started.json", make_native_start(
                    adapter=endpoint["adapter"], run_id=envelope.run_id, cell_id=envelope.cell_id,
                    message_id=envelope.message_id, request_sha256=envelope.payload_sha256,
                    native_request_sha256="c" * 64, native_task_kind="test-session",
                    native_task_id="native-one", native_task_status="RUNNING", pid=os.getpid()))
            else:
                assert (attempt / "started.json").read_bytes() == original_start
            return {"schema_version": "slk.temporal-delivery-update-result/v1", "status": "DELIVERY_REQUESTED",
                    "operation": "request_delivery", "run_id": envelope.run_id,
                    "operation_id": wc._stable_id(envelope.message_id, "temporal-delivery"),
                    "message_id": envelope.message_id}
        if arguments[0] == "native-started":
            return {"schema_version": "slk.temporal-delivery-update-result/v1", "status": "DELIVERY_ACKNOWLEDGED",
                    "operation": "native_started", "run_id": envelope.run_id,
                    "operation_id": wc._stable_id(envelope.message_id, "temporal-delivery"),
                    "message_id": envelope.message_id}
        if arguments[0] == "commit-delivery-start":
            return {"status": "committed", "message_id": envelope.message_id,
                    "runtime_revision": 8, "token_sequence": envelope.token_sequence,
                    "run_id": envelope.run_id,
                    "token_owner_role_instance_id": envelope.receiver_role_instance_id}
        pytest.fail(f"unexpected command: {command} {arguments}")

    monkeypatch.setattr(wc, "_run_json_command", command)
    if mode.endswith("drift"):
        with pytest.raises(wc.CompletionError, match="delivered output identity differs"):
            host._send_owned(source / "temporal-owned", envelope, "2026-10-05T00:00:00Z", projection,
                             register_delivered_output=True)
        assert all(kind == "authenticate-role" for _command, kind in calls)
        return
    result = host._send_owned(source / "temporal-owned", envelope, "2026-10-05T00:00:00Z", projection,
                              register_delivered_output=mode == "delivered")

    assert result["status"] == "OWNED_HANDOFF_COMMITTED"
    assert [kind for _command, kind in calls].count("request-delivery") == 1
    assert [kind for _command, kind in calls].count("native-started") == 1
    assert [kind for _command, kind in calls].count("commit-delivery-start") == 1
    assert all(command != "transport" for command, _kind in calls)
    if original_start is not None:
        assert (attempt / "started.json").read_bytes() == original_start
    attempt = canonical / envelope.run_id / envelope.message_id
    assert wc._read_object(attempt / "envelope.json", "staged envelope")["message_id"] == envelope.message_id


@pytest.mark.parametrize("status", ["BLOCKED", "RECOVERY_REQUIRED"])
def test_temporal_nonstart_result_is_recorded_and_fails_without_waiting(
    tmp_path: Path, monkeypatch, status: str,
) -> None:
    endpoint = checker_endpoint(tmp_path)
    envelope = candidate_envelope(tmp_path)
    binding = temporal_binding(tmp_path, tmp_path / "canonical-attempts")
    evidence = tmp_path / "evidence"
    monkeypatch.setattr(wc.time, "sleep", lambda _seconds: pytest.fail("non-start result must not poll"))

    def command(_command, arguments, **_kwargs):
        assert arguments[0] == "request-delivery"
        return {"schema_version": "slk.temporal-delivery-update-result/v1", "status": status,
                "operation": "request_delivery", "run_id": envelope.run_id,
                "operation_id": wc._stable_id(envelope.message_id, "temporal-delivery"),
                "message_id": envelope.message_id}

    monkeypatch.setattr(wc, "_run_json_command", command)
    with pytest.raises(wc.CompletionError, match=status):
        wc.start_temporal_delivery(binding, evidence, asdict(endpoint), asdict(envelope),
                                   attempt=1, source_runtime_revision=7)
    saved = list(evidence.glob(f"*.{status.lower().replace('_', '-')}.result.json"))
    assert len(saved) == 1
    assert wc._read_object(saved[0], "Temporal result")["status"] == status


def test_acknowledged_before_central_commit_retries_without_second_native_start(
    tmp_path: Path, monkeypatch,
) -> None:
    host, source, envelope = prepared_host(tmp_path)
    canonical = tmp_path / "canonical-attempts"
    host = RoleHost({**host.binding, "schema_version": "slk.role-host/v2",
                     "temporal": temporal_binding(tmp_path, canonical)}, "b" * 64)
    projection = host_boundary(host, envelope)
    monkeypatch.setattr(host, "projection", lambda: projection)
    monkeypatch.setattr(wc, "unprotect_dpapi_hex", lambda _p: "sealed-test-secret")
    requests = native_starts = acknowledgements = commit_attempts = successful_commits = 0

    def command(_command, arguments, **_kwargs):
        nonlocal requests, native_starts, acknowledgements, commit_attempts, successful_commits
        kind = arguments[0]
        if kind == "authenticate-role":
            return {"status": "authenticated", "run_id": envelope.run_id, "role": envelope.sender_role,
                    "role_instance_id": envelope.sender_role_instance_id, "runtime_revision": 7}
        if kind == "request-delivery":
            requests += 1
            status = "DELIVERY_REQUESTED" if requests == 1 else "DELIVERY_ACKNOWLEDGED"
            if requests == 1:
                native_starts += 1
                endpoint = host.endpoint(envelope.receiver_role)
                write_json(canonical / envelope.run_id / envelope.message_id / "started.json", make_native_start(
                    adapter=endpoint["adapter"], run_id=envelope.run_id, cell_id=envelope.cell_id,
                    message_id=envelope.message_id, request_sha256=envelope.payload_sha256,
                    native_request_sha256="c" * 64, native_task_kind="test-session",
                    native_task_id="native-one", native_task_status="RUNNING", pid=os.getpid()))
            return {"schema_version": "slk.temporal-delivery-update-result/v1", "status": status,
                    "operation": "request_delivery", "run_id": envelope.run_id,
                    "operation_id": wc._stable_id(envelope.message_id, "temporal-delivery"),
                    "message_id": envelope.message_id}
        if kind == "native-started":
            acknowledgements += 1
            return {"schema_version": "slk.temporal-delivery-update-result/v1",
                    "status": "DELIVERY_ACKNOWLEDGED", "operation": "native_started",
                    "run_id": envelope.run_id,
                    "operation_id": wc._stable_id(envelope.message_id, "temporal-delivery"),
                    "message_id": envelope.message_id}
        if kind == "commit-delivery-start":
            commit_attempts += 1
            if commit_attempts == 1:
                raise wc.CompletionError("SIMULATED_CRASH", "after ACK, before central commit")
            successful_commits += 1
            return {"status": "committed", "message_id": envelope.message_id,
                    "runtime_revision": 8, "token_sequence": envelope.token_sequence,
                    "run_id": envelope.run_id,
                    "token_owner_role_instance_id": envelope.receiver_role_instance_id}
        pytest.fail(f"unexpected command: {kind}")

    monkeypatch.setattr(wc, "_run_json_command", command)
    with pytest.raises(wc.CompletionError, match="before central commit"):
        host._send_owned(source / "interrupted", envelope, "2026-10-05T00:00:00Z", projection)
    result = host._send_owned(source / "interrupted", envelope, "2026-10-05T00:00:00Z", projection)

    assert result["status"] == "OWNED_HANDOFF_COMMITTED"
    assert requests == 1
    assert native_starts == acknowledgements == successful_commits == 1


def test_public_sender_host_continues_exact_staged_handoff_without_second_native_start(
    tmp_path: Path, monkeypatch,
) -> None:
    host, _source, envelope = prepared_host(tmp_path)
    canonical = tmp_path / "canonical-attempts"
    host = RoleHost({**host.binding, "schema_version": "slk.role-host/v2",
                     "temporal": temporal_binding(tmp_path, canonical)}, "b" * 64)
    source = canonical / envelope.run_id / envelope.message_id
    endpoint = host.endpoint(envelope.receiver_role)
    write_json(source / "endpoint.json", endpoint)
    write_json(source / "envelope.json", asdict(envelope))
    write_json(source / "started.json", make_native_start(
        adapter=endpoint["adapter"], run_id=envelope.run_id, cell_id=envelope.cell_id,
        message_id=envelope.message_id, request_sha256=envelope.payload_sha256,
        native_request_sha256="e" * 64, native_task_kind="test-session",
        native_task_id="native-existing", native_task_status="RUNNING", pid=os.getpid()))
    operation_id = wc._stable_id(envelope.message_id, "temporal-delivery")
    write_json(
        source / "role-host" / "sender-handoff"
        / f"temporal-native-started-{operation_id}.delivery-acknowledged.result.json",
        {"schema_version": "slk.temporal-delivery-update-result/v1",
         "status": "DELIVERY_ACKNOWLEDGED", "operation": "native_started",
         "run_id": envelope.run_id, "operation_id": operation_id,
         "message_id": envelope.message_id},
    )
    projection = host_boundary(host, envelope)
    monkeypatch.setattr(host, "projection", lambda: projection)
    monkeypatch.setattr(wc, "unprotect_dpapi_hex", lambda _p: "sealed-test-secret")
    calls: list[str] = []

    def command(_command, arguments, **_kwargs):
        kind = arguments[0]
        calls.append(kind)
        if kind == "authenticate-role":
            return {"status": "authenticated", "run_id": envelope.run_id,
                    "role": envelope.sender_role,
                    "role_instance_id": envelope.sender_role_instance_id,
                    "runtime_revision": 7}
        if kind == "commit-delivery-start":
            return {"status": "committed", "message_id": envelope.message_id,
                    "runtime_revision": 8, "token_sequence": envelope.token_sequence,
                    "run_id": envelope.run_id,
                    "token_owner_role_instance_id": envelope.receiver_role_instance_id}
        pytest.fail(f"existing native start must be commit-only, got {kind}")

    monkeypatch.setattr(wc, "_run_json_command", command)
    result = host.continue_staged_handoff(source)

    assert result["status"] == "OWNED_HANDOFF_COMMITTED"
    assert calls == ["authenticate-role", "authenticate-role", "commit-delivery-start"]


def test_public_sender_host_starts_one_not_yet_started_canonical_handoff(
    tmp_path: Path, monkeypatch,
) -> None:
    host, _source, envelope = prepared_host(tmp_path)
    canonical = tmp_path / "canonical-attempts"
    host = RoleHost({**host.binding, "schema_version": "slk.role-host/v2",
                     "temporal": temporal_binding(tmp_path, canonical)}, "b" * 64)
    source = canonical / envelope.run_id / envelope.message_id
    endpoint = host.endpoint(envelope.receiver_role)
    write_json(source / "endpoint.json", endpoint)
    write_json(source / "envelope.json", asdict(envelope))
    projection = host_boundary(host, envelope)
    monkeypatch.setattr(host, "projection", lambda: projection)
    monkeypatch.setattr(wc, "unprotect_dpapi_hex", lambda _p: "sealed-test-secret")
    starts: list[Path] = []

    def start(_binding, _root, target, raw_envelope, **_kwargs):
        starts.append(source)
        assert target == endpoint and raw_envelope == asdict(envelope)
        write_json(source / "started.json", make_native_start(
            adapter=endpoint["adapter"], run_id=envelope.run_id, cell_id=envelope.cell_id,
            message_id=envelope.message_id, request_sha256=envelope.payload_sha256,
            native_request_sha256="f" * 64, native_task_kind="test-session",
            native_task_id="native-new", native_task_status="RUNNING", pid=os.getpid()))
        return source

    def command(_command, arguments, **_kwargs):
        if arguments[0] == "authenticate-role":
            return {"status": "authenticated", "run_id": envelope.run_id,
                    "role": envelope.sender_role,
                    "role_instance_id": envelope.sender_role_instance_id,
                    "runtime_revision": 7}
        if arguments[0] == "commit-delivery-start":
            return {"status": "committed", "message_id": envelope.message_id,
                    "runtime_revision": 8, "token_sequence": envelope.token_sequence,
                    "run_id": envelope.run_id,
                    "token_owner_role_instance_id": envelope.receiver_role_instance_id}
        pytest.fail(f"unexpected command: {arguments[0]}")

    monkeypatch.setattr(wc, "start_temporal_delivery", start)
    monkeypatch.setattr(wc, "_run_json_command", command)

    assert host.continue_staged_handoff(source)["status"] == "OWNED_HANDOFF_COMMITTED"
    assert starts == [source]


@pytest.mark.parametrize("central_state", ["active", "pause_requested", "paused"])
def test_public_sender_host_acks_existing_external_operation_before_token_commit(
    tmp_path: Path, monkeypatch, central_state,
) -> None:
    host, _source, envelope = prepared_host(tmp_path)
    canonical = tmp_path / "canonical-attempts"
    host = RoleHost({**host.binding, "schema_version": "slk.role-host/v2",
                     "temporal": temporal_binding(tmp_path, canonical)}, "b" * 64)
    source = canonical / envelope.run_id / envelope.message_id
    endpoint = host.endpoint(envelope.receiver_role)
    write_json(source / "endpoint.json", endpoint)
    write_json(source / "envelope.json", asdict(envelope))
    write_json(source / "started.json", make_native_start(
        adapter=endpoint["adapter"], run_id=envelope.run_id, cell_id=envelope.cell_id,
        message_id=envelope.message_id, request_sha256=envelope.payload_sha256,
        native_request_sha256="1" * 64, native_task_kind="test-session",
        native_task_id="native-external", native_task_status="RUNNING", pid=os.getpid()))
    request = write_json(tmp_path / "original-temporal-request.json", {
        "operation_id": f"deliver-{envelope.message_id}", "run_id": envelope.run_id,
        "cell_id": envelope.cell_id, "attempt": 1, "message_id": envelope.message_id,
        "sender_role_instance_id": envelope.sender_role_instance_id,
        "receiver_role_instance_id": envelope.receiver_role_instance_id,
        "payload_sha256": envelope.payload_sha256, "source_runtime_revision": 4,
    })
    projection = host_boundary(host, envelope)
    projection["summary"]["state"] = central_state
    monkeypatch.setattr(host, "projection", lambda: projection)
    monkeypatch.setattr(wc, "unprotect_dpapi_hex", lambda _p: "sealed-test-secret")
    calls: list[str] = []

    def command(_command, arguments, **_kwargs):
        kind = arguments[0]
        calls.append(kind)
        if kind == "native-started":
            ack = json.loads(Path(arguments[arguments.index("--request") + 1]).read_text())
            assert ack["operation_id"] == f"deliver-{envelope.message_id}"
            assert ack["started_receipt_sha256"] == hashlib.sha256(
                (source / "started.json").read_bytes()).hexdigest()
            return {"schema_version": "slk.temporal-delivery-update-result/v1",
                    "status": "DELIVERY_ACKNOWLEDGED", "operation": "native_started",
                    "run_id": envelope.run_id, "operation_id": ack["operation_id"],
                    "message_id": envelope.message_id}
        if kind == "authenticate-role":
            return {"status": "authenticated", "run_id": envelope.run_id,
                    "role": envelope.sender_role,
                    "role_instance_id": envelope.sender_role_instance_id,
                    "runtime_revision": 7}
        if kind == "commit-delivery-start":
            if projection["summary"]["state"] == "paused":
                return {"status": "error", "code": "SLK_RUN_PAUSED", "message": "Run pause keeps new TOKEN commits fenced"}
            return {"status": "committed", "message_id": envelope.message_id,
                    "runtime_revision": 8, "token_sequence": envelope.token_sequence,
                    "run_id": envelope.run_id,
                    "token_owner_role_instance_id": envelope.receiver_role_instance_id}
        pytest.fail(f"existing native start must not repeat request-delivery, got {kind}")

    monkeypatch.setattr(wc, "_run_json_command", command)
    if central_state == "paused":
        with pytest.raises(wc.CompletionError, match="new TOKEN commits fenced"):
            host.continue_staged_handoff(source, temporal_request_path=request,
                temporal_request_sha256=hashlib.sha256(request.read_bytes()).hexdigest())
        # The original ACK was saved before the central fence rejected its TOKEN
        # commit. It can unblock same-pause confirmation; resume then commits the
        # original delivery, without another native start or ACK.
        assert calls == ["authenticate-role", "native-started", "authenticate-role", "commit-delivery-start"]
        projection["summary"]["state"] = "active"
        calls.clear()
    result = host.continue_staged_handoff(
        source,
        temporal_request_path=request,
        temporal_request_sha256=hashlib.sha256(request.read_bytes()).hexdigest(),
    )

    assert result["status"] == "OWNED_HANDOFF_COMMITTED"
    assert calls == (["authenticate-role", "authenticate-role", "commit-delivery-start"] if central_state == "paused"
        else ["authenticate-role", "native-started", "authenticate-role", "commit-delivery-start"])


def test_public_sender_host_rejects_noncanonical_staged_handoff_before_authentication(
    tmp_path: Path, monkeypatch,
) -> None:
    host, source, envelope = prepared_host(tmp_path)
    canonical = tmp_path / "canonical-attempts"
    host = RoleHost({**host.binding, "schema_version": "slk.role-host/v2",
                     "temporal": temporal_binding(tmp_path, canonical)}, "b" * 64)

    def forbidden(*_args, **_kwargs):
        pytest.fail("noncanonical source consumed a sealed credential")

    monkeypatch.setattr(wc, "unprotect_dpapi_hex", forbidden)
    with pytest.raises(wc.CompletionError, match="canonical Temporal attempt"):
        host.continue_staged_handoff(source)


def test_public_sender_host_rejects_existing_start_without_original_request_or_saved_ack(
    tmp_path: Path, monkeypatch,
) -> None:
    host, _source, envelope = prepared_host(tmp_path)
    canonical = tmp_path / "canonical-attempts"
    host = RoleHost({**host.binding, "schema_version": "slk.role-host/v2",
                     "temporal": temporal_binding(tmp_path, canonical)}, "b" * 64)
    source = canonical / envelope.run_id / envelope.message_id
    endpoint = host.endpoint(envelope.receiver_role)
    write_json(source / "endpoint.json", endpoint)
    write_json(source / "envelope.json", asdict(envelope))
    write_json(source / "started.json", make_native_start(
        adapter=endpoint["adapter"], run_id=envelope.run_id, cell_id=envelope.cell_id,
        message_id=envelope.message_id, request_sha256=envelope.payload_sha256,
        native_request_sha256="2" * 64, native_task_kind="test-session",
        native_task_id="native-unacked", native_task_status="RUNNING", pid=os.getpid()))
    projection = host_boundary(host, envelope)
    monkeypatch.setattr(host, "projection", lambda: projection)
    monkeypatch.setattr(wc, "unprotect_dpapi_hex", lambda _p: "sealed-test-secret")

    def command(_command, arguments, **_kwargs):
        if arguments[0] == "authenticate-role":
            return {"status": "authenticated", "run_id": envelope.run_id,
                    "role": envelope.sender_role,
                    "role_instance_id": envelope.sender_role_instance_id,
                    "runtime_revision": 7}
        pytest.fail("unacknowledged start reached an external continuation side effect")

    monkeypatch.setattr(wc, "_run_json_command", command)
    with pytest.raises(wc.CompletionError) as rejected:
        host.continue_staged_handoff(source)

    assert rejected.value.error_code == "TEMPORAL_NATIVE_ACK_UNPROVED"


def test_legacy_role_host_without_temporal_binding_keeps_direct_transport_compatibility(
    tmp_path: Path, monkeypatch,
) -> None:
    host, source, envelope = prepared_host(tmp_path)
    projection = host_boundary(host, envelope)
    monkeypatch.setattr(host, "projection", lambda: projection)
    monkeypatch.setattr(wc, "unprotect_dpapi_hex", lambda _p: "sealed-test-secret")
    calls: list[str] = []

    def command(command, arguments, **_kwargs):
        calls.append(arguments[0])
        if arguments[0] == "authenticate-role":
            return {"status": "authenticated", "run_id": envelope.run_id, "role": envelope.sender_role,
                    "role_instance_id": envelope.sender_role_instance_id, "runtime_revision": 7}
        if arguments[0] == "send":
            root = Path(arguments[arguments.index("--attempt-root") + 1])
            endpoint = host.endpoint(envelope.receiver_role)
            attempt = root / envelope.run_id / envelope.message_id
            write_json(attempt / "endpoint.json", endpoint)
            write_json(attempt / "envelope.json", asdict(envelope))
            write_json(attempt / "started.json", make_native_start(
                adapter=endpoint["adapter"], run_id=envelope.run_id, cell_id=envelope.cell_id,
                message_id=envelope.message_id, request_sha256=envelope.payload_sha256,
                native_request_sha256="d" * 64, native_task_kind="legacy-test",
                native_task_id="legacy-one", native_task_status="RUNNING", pid=os.getpid()))
            return {"status": "started", "run_id": envelope.run_id, "message_id": envelope.message_id}
        if arguments[0] == "commit-delivery-start":
            return {"status": "committed", "message_id": envelope.message_id,
                    "runtime_revision": 8, "token_sequence": envelope.token_sequence,
                    "run_id": envelope.run_id,
                    "token_owner_role_instance_id": envelope.receiver_role_instance_id}
        pytest.fail(f"unexpected command: {command} {arguments}")

    monkeypatch.setattr(wc, "_run_json_command", command)
    assert host._send_owned(source / "legacy-owned", envelope, "2026-10-05T00:00:00Z", projection)["status"] == "OWNED_HANDOFF_COMMITTED"
    assert calls.count("send") == 1
    assert "request-delivery" not in calls and "native-started" not in calls
