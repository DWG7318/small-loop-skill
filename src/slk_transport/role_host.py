"""Ordinary transport-job suffixes. No scheduler, Agent, or parallel state store.

The preparation host freezes this local binding. Models receive only their task
and return engineering results; sealed credentials remain in this host process.
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from . import worker_completion as wc
from .contracts import SHA256, DeliveryResult, Endpoint, Envelope, canonical_json_sha256, parse_delivery
from .native_activity import validate_native_start


FIELDS = {"schema_version", "run_id", "plan_revision", "state_command", "transport_command", "roles", "cells", "d2_criteria"}
FIELDS_V2 = FIELDS | {"temporal"}
ROLE_FIELDS = {"endpoint_path", "endpoint_sha256", "credential_path"}


def load_role_host(endpoint_raw: Mapping[str, Any]) -> "RoleHost | None":
    path_value = os.environ.get("SLK_TRANSPORT_ROLE_HOST")
    digest = os.environ.get("SLK_TRANSPORT_ROLE_HOST_SHA256")
    if path_value is None and digest is None:
        return None  # historical transports; new readiness requires the bound path
    try:
        path = Path(path_value or "")
        if not path.is_absolute() or path.stat().st_size > 131072 or wc._sha256(path) != digest:
            raise ValueError("missing or changed host binding")
        host = RoleHost(wc._read_object(path, "role host binding"), str(digest))
        endpoint = Endpoint.from_dict(endpoint_raw)
        if host.endpoint(endpoint.role) != dict(endpoint_raw):
            raise ValueError("host binding does not match the registered receiver")
        return host
    except (OSError, TypeError, KeyError, ValueError) as exc:
        raise wc.CompletionError("ROLE_HOST_BINDING_INVALID", "preparation host binding is unavailable or changed") from exc


class RoleHost:
    def __init__(self, binding: Mapping[str, Any], digest: str, *, state_config_path: str | None = None):
        schema_version = binding.get("schema_version")
        expected_fields = FIELDS_V2 if schema_version == "slk.role-host/v2" else FIELDS
        if (set(binding) != expected_fields or schema_version not in {"slk.role-host/v1", "slk.role-host/v2"}
            or not isinstance(binding.get("roles"), Mapping) or set(binding["roles"]) != {"supervisor", "checker", "worker"}
            or type(binding.get("plan_revision")) is not int or binding["plan_revision"] < 1
            or not isinstance(binding.get("cells"), list) or not binding["cells"]):
            raise ValueError("host binding is not closed")
        for field in ("state_command", "transport_command", "d2_criteria"):
            if not isinstance(binding[field], list) or not binding[field] or not all(isinstance(x, str) and x.strip() for x in binding[field]):
                raise ValueError("host command or criteria are invalid")
        self.binding, self.digest = dict(binding), digest
        if schema_version == "slk.role-host/v2":
            self.binding["temporal"] = wc.validate_temporal_binding(binding["temporal"], str(binding["run_id"]))
        self.state_config_path = state_config_path
        self.state = list(binding["state_command"])
        self.transport = list(binding["transport_command"])
        self.endpoints = {}
        identities = set()
        for role, value in binding["roles"].items():
            if not isinstance(value, Mapping) or set(value) != ROLE_FIELDS:
                raise ValueError("host role is not closed")
            path = Path(value["endpoint_path"])
            credential = Path(value["credential_path"])
            if not path.is_absolute() or wc._sha256(path) != value["endpoint_sha256"] or not credential.is_absolute() or not credential.is_file():
                raise ValueError("host endpoint or sealed credential is missing")
            raw = wc._read_object(path, "host endpoint")
            endpoint = Endpoint.from_dict(raw)
            if endpoint.run_id != binding["run_id"] or endpoint.role != role or endpoint.state != "active" or endpoint.role_instance_id in identities:
                raise ValueError("host role identity differs")
            identities.add(endpoint.role_instance_id)
            self.endpoints[role] = raw
        ids = []
        for cell in binding["cells"]:
            if not isinstance(cell, Mapping) or set(cell) != {"go_id", "cell_id", "payload"} or not isinstance(cell["payload"], Mapping):
                raise ValueError("frozen CELL dispatch is not closed")
            ids.append(cell["cell_id"])
        if len(set(ids)) != len(ids):
            raise ValueError("duplicate CELL binding")
        # Subsequent dispatches use the existing closed Checker NEXT_CELL
        # contract. Reject an unusable plan before the first native dispatch.
        from .checker_completion import _validate_payload, _text, _strings
        first = binding["cells"][0]
        payload = first["payload"]
        if "task" in payload:
            _validate_payload({"route": "NEXT_CELL", "target_cell_id": first["cell_id"],
                               "payload": payload}, binding["cells"], {})
        else:
            if not {"cell_goal", "d1_criteria"} <= set(payload) <= {"cell_goal", "d1_criteria", "instructions"}:
                raise ValueError("initial frozen Worker task is not closed")
            _text(payload["cell_goal"], "initial CELL goal")
            _strings(payload["d1_criteria"], "initial D1 criteria")
            if "instructions" in payload:
                _text(payload["instructions"], "initial CELL instructions")
        for cell in binding["cells"][1:]:
            _validate_payload({"route": "NEXT_CELL", "target_cell_id": cell["cell_id"],
                               "payload": cell["payload"]}, binding["cells"], {})

    def endpoint(self, role: str) -> dict[str, Any]:
        return dict(self.endpoints[role])

    def credential_path(self, role: str) -> str:
        return str(self.binding["roles"][role]["credential_path"])

    def projection(self) -> Mapping[str, Any]:
        if self.state_config_path is None:
            return wc._default_load_current_projection(str(self.binding["run_id"]), self.state)
        return wc._default_load_current_projection(str(self.binding["run_id"]), self.state,
                                                   state_config_path=self.state_config_path)

    def _state_json(self, arguments: list[str], *, credential: str | None) -> Mapping[str, Any]:
        if self.state_config_path is None:
            return wc._run_json_command(self.state, arguments, credential=credential)
        return wc._run_json_command(self.state, arguments, credential=credential,
                                    state_config_path=self.state_config_path)

    def _authenticate(self, role: str, credential: str) -> Mapping[str, Any]:
        endpoint = self.endpoint(role)
        value = self._state_json(["authenticate-role", "--run-id", endpoint["run_id"],
                                  "--role-instance-id", endpoint["role_instance_id"]], credential=credential)
        if (value.get("status") != "authenticated" or value.get("run_id") != endpoint["run_id"]
            or value.get("role") != role or value.get("role_instance_id") != endpoint["role_instance_id"]
            or type(value.get("runtime_revision")) is not int or value["runtime_revision"] < 1):
            raise wc.CompletionError("ROLE_HOST_AUTHORITY_INVALID", "sealed credential does not authenticate its registered role")
        return value

    def _boundary(self, envelope: Envelope) -> Mapping[str, Any]:
        # Native start and TOKEN commit are separate. The parent host must finish
        # the latter before a fast receiver performs its deterministic suffix.
        deadline = time.monotonic() + 10
        while True:
            projection = self.projection()
            snapshot = projection.get("runtime_snapshot", {})
            if snapshot.get("plan_revision") != self.binding["plan_revision"]:
                raise wc.CompletionError("ROLE_HOST_PLAN_CHANGED", "prepared host plan has been superseded")
            try:
                boundary = wc.resolve_authoritative_token_boundary(
                    projection, run_id=envelope.run_id, plan_revision=self.binding["plan_revision"])
            except wc.CompletionError:
                boundary = None
            if (boundary is not None and boundary["message_id"] == envelope.message_id
                and boundary["token_sequence"] == envelope.token_sequence
                and boundary["holder_role_instance_id"] == envelope.receiver_role_instance_id
                and boundary["go_id"] in {None, envelope.go_id}
                and boundary["cell_id"] in {None, envelope.cell_id}):
                return projection
            if time.monotonic() >= deadline:
                raise wc.CompletionError("ROLE_HOST_TOKEN_UNCONFIRMED", "receiver started but the exact TOKEN commit is not confirmed")
            time.sleep(0.05)

    def complete(self, source: Path) -> dict[str, Any]:
        envelope = Envelope.from_dict(wc._read_object(source / "envelope.json", "source envelope"))
        role = envelope.receiver_role
        if wc._read_object(source / "endpoint.json", "source endpoint") != self.endpoint(role):
            raise wc.CompletionError("ROLE_HOST_BINDING_INVALID", "source receiver is not the prepared role")
        root = source / "role-host"
        root.mkdir(parents=True, exist_ok=True)
        result_path = root / "result.json"
        source_sha256 = canonical_json_sha256({name: wc._sha256(source / name) for name in (
            "endpoint.json", "envelope.json", "started.json", "completed.json", "failed.json",
            "worker-result.json", "checker-result.json", "ocrv-result.json", "supervisor-result.json") if (source / name).is_file()})
        handoff_evidence = source / "incomplete-handoff" / "evidence.json"
        if handoff_evidence.is_file():
            source_sha256 = canonical_json_sha256({"source": source_sha256,
                                                   "incomplete-handoff/evidence.json": wc._sha256(handoff_evidence)})
        if result_path.exists():
            saved = wc._read_object(result_path, "owned handoff receipt")
            if (saved.get("binding_sha256") != self.digest or saved.get("source_message_id") != envelope.message_id
                or saved.get("source_sha256") != source_sha256):
                raise wc.CompletionError("ROLE_HOST_CONFLICT", "owned handoff receipt changed identity")
            return saved
        incomplete_worker = (role == "worker" and not (source / "completed.json").is_file()
                             and (source / "failed.json").is_file() and handoff_evidence.is_file())
        if not (source / "completed.json").is_file() and not incomplete_worker:
            return {"status": "ENGINEERING_RESULT_INCOMPLETE", "source_message_id": envelope.message_id}
        if not incomplete_worker:
            self._completion_proof(source, envelope)
        projection = None if role == "supervisor" else self._boundary(envelope)
        terminal = source / ("failed.json" if incomplete_worker else "completed.json")
        occurred_at = datetime.fromtimestamp(terminal.stat().st_mtime, timezone.utc).isoformat()
        if role == "supervisor":
            result = self._supervisor_result(source, envelope, root, occurred_at)
        elif role == "worker":
            request_path = root / "continuation.json"
            if request_path.exists():
                request = wc._read_object(request_path, "owned Worker continuation")
            else:
                snapshot = projection["runtime_snapshot"]
                request = wc.build_continuation_request(source, self.endpoint("checker"), projection,
                    plan_revision=self.binding["plan_revision"], runtime_revision=snapshot["runtime_revision"],
                    token_sequence=snapshot["token_sequence"], credential_path=self.credential_path(role),
                    state_command=self.state, transport_command=self.transport, occurred_at=occurred_at,
                    temporal=self.binding.get("temporal"))
                wc._write_or_reuse_stable_request(request_path, request)
            result = wc.execute_worker_host_continuation(request)
        elif envelope.payload_type == "CELL_DISPATCH":
            result = wc._read_object(source / "checker-result.json", "Checker dispatch")
            outgoing = self._dispatch_envelope(envelope, result)
            result = self._send_owned(root, outgoing, occurred_at, projection)
        elif envelope.payload_type == "CANDIDATE_READY":
            result = self._checker_result(source, envelope, root, occurred_at, projection)
        else:
            raise wc.CompletionError("ROLE_HOST_OPERATION_INVALID", "no normal suffix for this operation")
        result = {**result, "binding_sha256": self.digest, "source_message_id": envelope.message_id,
                  "source_sha256": source_sha256}
        wc._write_or_reuse_stable_request(result_path, result)
        return result

    def _dispatch_envelope(self, incoming: Envelope, result: Mapping[str, Any]) -> Envelope:
        try:
            outgoing = parse_delivery(self.endpoint("worker"), result["next_envelope"]).envelope
            frozen = next((c for c in self.binding["cells"] if c["cell_id"] == incoming.cell_id), None)
            valid = (set(result) == {"schema_version", "operation", "source_message_id", "next_endpoint", "next_envelope"}
                and result.get("schema_version") == "slk.checker-result/v1" and result.get("operation") == "dispatch"
                and result.get("source_message_id") == incoming.message_id and result["next_endpoint"] == self.endpoint("worker")
                and frozen is not None and frozen["go_id"] == incoming.go_id and outgoing.payload == frozen["payload"]
                and (outgoing.run_id, outgoing.go_id, outgoing.cell_id) == (incoming.run_id, incoming.go_id, incoming.cell_id)
                and outgoing.token_sequence == incoming.token_sequence + 1 and outgoing.payload_type == "WORKER_TASK"
                and outgoing.sender_role == "checker" and outgoing.sender_role_instance_id == incoming.receiver_role_instance_id)
        except (KeyError, TypeError, ValueError):
            valid = False
        if not valid:
            raise wc.CompletionError("ROLE_HOST_DISPATCH_INVALID", "dispatch differs from the frozen CELL or incoming responsibility")
        return outgoing

    def _completion_proof(self, source: Path, envelope: Envelope) -> None:
        try:
            endpoint = self.endpoint(envelope.receiver_role)
            parse_delivery(endpoint, wc._read_object(source / "envelope.json", "source envelope"))
            terminal = DeliveryResult.from_dict(wc._read_object(source / "completed.json", "source terminal"))
            native = validate_native_start(source / "started.json", adapter=endpoint["adapter"],
                run_id=envelope.run_id, cell_id=envelope.cell_id, message_id=envelope.message_id,
                request_sha256=envelope.payload_sha256)
            if ((source / "failed.json").exists() or terminal.status != "completed" or terminal.error_code is not None
                or terminal.run_id != envelope.run_id or terminal.message_id != envelope.message_id
                or terminal.adapter != endpoint["adapter"]):
                raise ValueError("terminal does not prove this completed delivery")
            if envelope.receiver_role == "supervisor":
                identity = terminal.native_identity
                fields = {"thread_id", "turn_id", "turn_status"}
                desktop = "desktop" in endpoint["address"]
                fields.add("platform_item_id" if desktop else "turn_sha256")
                if (set(identity) != fields or identity.get("thread_id") != endpoint["address"]["thread_id"]
                    or identity.get("turn_status") != "completed"
                    or any(not isinstance(identity.get(k), str) or not identity[k] for k in fields)):
                    raise ValueError("terminal changed the Supervisor native identity")
                task_id = f"{identity['thread_id']}:{identity['turn_id']}"
                if desktop: task_id += f":{identity['platform_item_id']}"
                elif not SHA256.fullmatch(identity["turn_sha256"]):
                    raise ValueError("native completed turn hash is invalid")
                if (native["native_task"]["id"] != task_id
                    or native["native_task"]["kind"] != ("codex-desktop-turn" if desktop else "codex-turn")):
                    raise ValueError("native start and completed turn differ")
        except (OSError, KeyError, ValueError) as exc:
            raise wc.CompletionError("ROLE_HOST_COMPLETION_UNPROVEN", "native completion does not match this source") from exc

    def _supervisor_result(self, source: Path, envelope: Envelope, root: Path, occurred_at: str) -> dict[str, Any]:
        """Consume the native Supervisor's decision, never derive a verdict."""
        from dataclasses import asdict
        result = wc._read_object(source / "supervisor-result.json", "Supervisor decision")
        operation = {"D1_FAILURE_ESCALATION": "rework", "D2_READY": "d2"}.get(envelope.payload_type)
        if (set(result) != {"schema_version", "source_message_id", "operation", "decision"}
            or result.get("schema_version") != "slk.supervisor-result/v1"
            or result.get("source_message_id") != envelope.message_id or operation is None
            or result.get("operation") != operation or not isinstance(result.get("decision"), Mapping)):
            raise wc.CompletionError("SUPERVISOR_RESULT_INVALID", "decision does not bind the native incoming responsibility")
        decision, outgoing = result["decision"], None
        if operation == "rework":
            for key in ("d1_failure_event_id", "failed_candidate_sha256", "rework_round", "cell_goal", "acceptance_criteria", "findings"):
                if decision.get(key) != envelope.payload.get(key):
                    raise wc.CompletionError("SUPERVISOR_RESULT_INVALID", "rework changed the original D1 or acceptance")
            worker = self.endpoint("worker")
            outgoing = parse_delivery(worker, {**asdict(envelope),
                "message_id": wc._stable_id(envelope.message_id, "supervisor-rework"),
                "token_sequence": envelope.token_sequence + 1, "sender_role": "supervisor",
                "sender_role_instance_id": envelope.receiver_role_instance_id,
                "receiver_role": "worker", "receiver_role_instance_id": worker["role_instance_id"],
                "receiver_endpoint_version": worker["endpoint_version"], "payload_type": "D1_REWORK_DIRECTIVE",
                "payload": decision, "payload_sha256": canonical_json_sha256(decision)}).envelope
            events = [("REWORK_REQUESTED", {key: decision[key] for key in (
                "d1_failure_event_id", "failed_candidate_sha256", "rework_round", "investigation_mode")})]
        else:
            if (set(decision) != {"verdict", "summary", "evidence_refs"}
                or decision.get("verdict") not in {"PASS", "FAIL", "INCOMPLETE"}
                or not isinstance(decision.get("summary"), str) or not decision["summary"].strip()):
                raise wc.CompletionError("SUPERVISOR_RESULT_INVALID", "D2 must contain the Supervisor's explicit verdict and evidence")
            events = [] if decision["verdict"] == "INCOMPLETE" else [
                ("D2_STARTED", {"source_message_id": envelope.message_id}),
                ("D2_PASSED" if decision["verdict"] == "PASS" else "D2_FAILED", dict(decision))]
        evidence = decision.get("evidence_refs")
        if (not isinstance(evidence, list) or not evidence or not all(
            isinstance(p, str) and Path(p).is_absolute() and Path(p).is_file() for p in evidence)):
            raise wc.CompletionError("SUPERVISOR_RESULT_INVALID", "decision evidence is not readable local evidence")
        wc._write_or_reuse_stable_request(root / "supervisor-decision.json", result)
        if outgoing is not None:
            attempts = (Path(str(self.binding["temporal"]["attempt_root"]))
                        if "temporal" in self.binding else root / "rework" / "attempts")
            native = attempts / outgoing.run_id / outgoing.message_id
            if self._committed_delivery(self.projection(), outgoing, native):
                credential = wc.unprotect_dpapi_hex(self.credential_path("supervisor"))
                try:
                    self._authenticate("supervisor", credential)
                finally:
                    credential = ""
                return {"status": "OWNED_HANDOFF_ALREADY_COMMITTED", "message_id": outgoing.message_id,
                        "native_attempt_path": str(native)}
        projection = self._boundary(envelope)
        credential = wc.unprotect_dpapi_hex(self.credential_path("supervisor"))
        try:
            self._authenticate("supervisor", credential)
            for event_type, details in events:
                request = {"event_id": wc._stable_id(envelope.message_id, event_type.lower()),
                    "run_id": envelope.run_id, "go_id": envelope.go_id if outgoing else None,
                    "cell_id": envelope.cell_id if outgoing else None,
                    "attempt": wc._source_attempt(projection, envelope) if outgoing else None,
                    "plan_revision": self.binding["plan_revision"], "role_instance_id": envelope.receiver_role_instance_id,
                    "event_type": event_type, "details": details, "corrects_event_id": None, "occurred_at": occurred_at}
                path = wc._write_or_reuse_stable_request(root / f"{event_type.lower()}.json", request)
                written = self._state_json(["write", "--request", str(path)], credential=credential)
                if written.get("status") != "recorded" or written.get("run_id") != envelope.run_id:
                    raise wc.CompletionError("SUPERVISOR_STATE_WRITE_FAILED", "Supervisor event was not recorded")
        finally:
            credential = ""
        if outgoing is not None:
            return self._send_owned(root / "rework", outgoing, occurred_at, self.projection())
        return {"status": "SUPERVISOR_D2_INCOMPLETE" if not events else "SUPERVISOR_D2_RECORDED", "verdict": decision["verdict"]}

    def _send_owned(self, root: Path, envelope: Envelope, occurred_at: str, projection: Mapping[str, Any]) -> dict[str, Any]:
        from dataclasses import asdict
        target = self.endpoint(envelope.receiver_role)
        sender = self.endpoint(envelope.sender_role)
        if (envelope.run_id != self.binding["run_id"]
            or envelope.sender_role_instance_id != sender["role_instance_id"]
            or envelope.receiver_role_instance_id != target["role_instance_id"]
            or envelope.receiver_endpoint_version != target["endpoint_version"]):
            raise wc.CompletionError("ROLE_HOST_BINDING_INVALID", "handoff changed the frozen role identity")
        credential = wc.unprotect_dpapi_hex(self.credential_path(envelope.sender_role))
        try:
            self._authenticate(envelope.sender_role, credential)
        finally:
            credential = ""
        latest = self.projection()
        attempts = (Path(str(self.binding["temporal"]["attempt_root"]))
                    if "temporal" in self.binding else root / "attempts")
        native = attempts / envelope.run_id / envelope.message_id
        if self._committed_delivery(latest, envelope, native):
            return {"status": "OWNED_HANDOFF_ALREADY_COMMITTED", "message_id": envelope.message_id,
                    "native_attempt_path": str(native)}
        current = latest.get("runtime_snapshot", {})
        try:
            prepared_boundary = wc.resolve_authoritative_token_boundary(
                projection, run_id=envelope.run_id, plan_revision=self.binding["plan_revision"])
            current_boundary = wc.resolve_authoritative_token_boundary(
                latest, run_id=envelope.run_id, plan_revision=self.binding["plan_revision"])
        except wc.CompletionError as exc:
            raise wc.CompletionError("ROLE_HOST_BOUNDARY_CHANGED", "sender TOKEN boundary is not authoritative") from exc
        if (current.get("plan_revision") != self.binding["plan_revision"]
            or current.get("token_holder_role_instance_id") != envelope.sender_role_instance_id
            or current.get("token_sequence") != envelope.token_sequence - 1
            or tuple(current_boundary[key] for key in ("message_id", "token_sequence", "holder_role_instance_id"))
               != tuple(prepared_boundary[key] for key in ("message_id", "token_sequence", "holder_role_instance_id"))):
            raise wc.CompletionError("ROLE_HOST_BOUNDARY_CHANGED", "sender does not own the exact prepared handoff")
        attempt_number = self._outgoing_attempt(envelope, latest)
        root.mkdir(parents=True, exist_ok=True)
        endpoint_path = wc._write_or_reuse_stable_request(root / "endpoint.json", target)
        envelope_path = wc._write_or_reuse_stable_request(root / "envelope.json", asdict(envelope))
        if "temporal" in self.binding:
            revision = latest.get("runtime_snapshot", {}).get("runtime_revision")
            if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
                raise wc.CompletionError("ROLE_HOST_BOUNDARY_CHANGED", "source runtime revision is unavailable")
            native = wc.start_temporal_delivery(
                self.binding["temporal"], root, target, asdict(envelope),
                attempt=attempt_number, source_runtime_revision=revision,
                required_attempt_root=attempts,
            )
        elif not native.exists():
            wc._run_json_command(self.transport, ["send", "--endpoint", str(endpoint_path), "--envelope", str(envelope_path),
                                                  "--attempt-root", str(attempts)], credential=None)
        started_path = native / "started.json"
        validate_native_start(started_path, adapter=target["adapter"], run_id=envelope.run_id,
                              cell_id=envelope.cell_id, message_id=envelope.message_id, request_sha256=envelope.payload_sha256)
        if (wc._read_object(native / "endpoint.json", "target endpoint") != target
            or wc._read_object(native / "envelope.json", "target envelope") != asdict(envelope)):
            raise wc.CompletionError("ROLE_HOST_START_INVALID", "native delivery identity differs")
        credential = wc.unprotect_dpapi_hex(self.credential_path(envelope.sender_role))
        try:
            auth = self._authenticate(envelope.sender_role, credential)
            current_projection = self.projection()
            current = current_projection["runtime_snapshot"]
            try:
                current_boundary = wc.resolve_authoritative_token_boundary(
                    current_projection, run_id=envelope.run_id, plan_revision=self.binding["plan_revision"])
            except wc.CompletionError as exc:
                raise wc.CompletionError("ROLE_HOST_BOUNDARY_CHANGED", "remaining TOKEN boundary is not authoritative") from exc
            if (current.get("token_holder_role_instance_id") != envelope.sender_role_instance_id
                or current.get("plan_revision") != self.binding["plan_revision"]
                or current.get("token_sequence") != envelope.token_sequence - 1
                or tuple(current_boundary[key] for key in ("message_id", "token_sequence", "holder_role_instance_id"))
                   != tuple(prepared_boundary[key] for key in ("message_id", "token_sequence", "holder_role_instance_id"))):
                raise wc.CompletionError("ROLE_HOST_BOUNDARY_CHANGED", "only the exact remaining start commit is permitted")
            request = {"event_id": wc._stable_id(envelope.message_id, "host-transport-started"),
                "transport_receipt_id": wc._stable_id(envelope.message_id, "host-start-receipt"),
                "run_id": envelope.run_id, "go_id": envelope.go_id, "cell_id": envelope.cell_id,
                "attempt": attempt_number, "plan_revision": self.binding["plan_revision"], "expected_runtime_revision": auth["runtime_revision"],
                "message_id": envelope.message_id, "token_sequence": envelope.token_sequence,
                "from_role_instance_id": envelope.sender_role_instance_id, "to_role_instance_id": envelope.receiver_role_instance_id,
                "endpoint_version": envelope.receiver_endpoint_version, "payload_type": envelope.payload_type,
                "payload_sha256": envelope.payload_sha256, "occurred_at": occurred_at,
                "start_evidence": {"evidence_id": wc._stable_id(envelope.message_id, "host-native-start"),
                    "stored_path": str(started_path), "sha256": wc._sha256(started_path), "message_id": envelope.message_id,
                    "endpoint_sha256": wc._sha256(native / "endpoint.json"), "envelope_sha256": wc._sha256(native / "envelope.json"), "native_status": "STARTED"}}
            path = root / "commit-delivery-start.json"
            if path.is_file():
                previous = wc._read_object(path, "original start commit")
                if previous != request:
                    old_revision = previous.get("expected_runtime_revision")
                    if (type(old_revision) is not int or old_revision >= auth["runtime_revision"]
                        or {**previous, "expected_runtime_revision": auth["runtime_revision"]} != request):
                        raise wc.CompletionError("ROLE_HOST_CONFLICT", "commit-only retry changed delivery facts")
                    path = root / "commit-only" / f"revision-{auth['runtime_revision']}.json"
                    path.parent.mkdir(parents=True, exist_ok=True)
            path = wc._write_or_reuse_stable_request(path, request)
            value = self._state_json(["commit-delivery-start", "--request", str(path)], credential=credential)
            if (value.get("status") not in {"committed", "idempotent_replay"}
                or value.get("message_id") != envelope.message_id or value.get("run_id") != envelope.run_id
                or type(value.get("runtime_revision")) is not int or value["runtime_revision"] != auth["runtime_revision"] + 1
                or value.get("token_sequence") != envelope.token_sequence
                or value.get("token_owner_role_instance_id") != envelope.receiver_role_instance_id):
                raise wc.CompletionError("ROLE_HOST_COMMIT_FAILED", "owned handoff commit did not match")
            wc._write_or_reuse_stable_request(path.with_suffix(".result.json"), value)
            return {"status": "OWNED_HANDOFF_COMMITTED", "message_id": envelope.message_id, "commit_path": str(path)}
        finally:
            credential = ""

    @staticmethod
    def _outgoing_attempt(envelope: Envelope, projection: Mapping[str, Any]) -> int:
        if envelope.payload_type != "D1_REWORK_DIRECTIVE":
            return 1
        matches = []
        for event in projection.get("events", []):
            if (event.get("event_type") != "REWORK_REQUESTED" or event.get("cell_id") != envelope.cell_id
                or event.get("go_id") != envelope.go_id):
                continue
            details = wc._event_details(event)
            if details and all(details.get(k) == envelope.payload[k] for k in (
                "d1_failure_event_id", "failed_candidate_sha256", "rework_round", "investigation_mode")):
                matches.append(event.get("attempt"))
        if len(matches) != 1 or type(matches[0]) is not int or matches[0] < 1:
            raise wc.CompletionError("ROLE_HOST_REWORK_UNPROVEN", "rework must bind one recorded original attempt")
        return matches[0] + 1

    def _committed_delivery(self, projection: Mapping[str, Any], envelope: Envelope, native: Path) -> bool:
        """Read existing central facts, not the latest TOKEN alone or a local success flag."""
        from dataclasses import asdict
        tokens = [item for item in projection.get("token_history", [])
                  if item.get("message_id") == envelope.message_id]
        events = []
        for event in projection.get("events", []):
            if event.get("event_type") != "TRANSPORT_STARTED":
                continue
            details = json.loads(event["details_json"])
            if details.get("message_id") == envelope.message_id:
                events.append((event, details))
        if not tokens and not events:
            return False
        if (projection.get("summary", {}).get("run_id") != envelope.run_id
            or len(tokens) != 1 or len(events) != 1):
            raise wc.CompletionError("ROLE_HOST_CONFLICT", "central handoff evidence is incomplete or duplicated")
        token, (event, details) = tokens[0], events[0]
        expected = {"event_type": "TOKEN_HANDED_OFF", "token_sequence": envelope.token_sequence,
            "go_id": envelope.go_id, "cell_id": envelope.cell_id,
            "from_role_instance_id": envelope.sender_role_instance_id,
            "to_role_instance_id": envelope.receiver_role_instance_id}
        if (any(token.get(k) != v for k, v in expected.items())
            or event.get("author_role_instance_id") != envelope.sender_role_instance_id
            or event.get("go_id") != envelope.go_id or event.get("cell_id") != envelope.cell_id
            or event.get("corrects_event_id") is not None):
            raise wc.CompletionError("ROLE_HOST_CONFLICT", "central handoff changed scope or role")
        try:
            validate_native_start(native / "started.json", adapter=self.endpoint(envelope.receiver_role)["adapter"],
                run_id=envelope.run_id, cell_id=envelope.cell_id, message_id=envelope.message_id,
                request_sha256=envelope.payload_sha256)
            exact = (wc._read_object(native / "endpoint.json", "committed endpoint") == self.endpoint(envelope.receiver_role)
                and wc._read_object(native / "envelope.json", "committed envelope") == asdict(envelope)
                and all(details.get(key) == wc._sha256(native / name) for key, name in (
                    ("start_evidence_sha256", "started.json"), ("endpoint_sha256", "endpoint.json"),
                    ("envelope_sha256", "envelope.json"))))
        except (OSError, ValueError) as exc:
            raise wc.CompletionError("ROLE_HOST_CONFLICT", "committed native evidence is unavailable") from exc
        if not exact:
            raise wc.CompletionError("ROLE_HOST_CONFLICT", "committed native evidence changed")
        return True

    def _checker_result(self, source: Path, envelope: Envelope, root: Path, occurred_at: str,
                        projection: Mapping[str, Any]) -> dict[str, Any]:
        from . import checker_completion as passed, checker_escalation as failed

        attempt = wc._source_attempt(projection, envelope)
        continuation = {"run_id": envelope.run_id, "go_id": envelope.go_id, "cell_id": envelope.cell_id,
                        "attempt": attempt, "plan_revision": self.binding["plan_revision"],
                        "checker_endpoint": self.endpoint("checker"), "state_command": self.state, "occurred_at": occurred_at}
        recorded = wc._record_checker_d1({"native_attempt_path": str(source), "candidate_message_id": envelope.message_id},
                                        continuation, checker_credential_path=self.credential_path("checker"), timeout_seconds=1)
        if recorded["d1_verdict"] == "INCOMPLETE":
            return recorded
        projection = self.projection()
        snapshot = projection["runtime_snapshot"]
        projection_path = wc._write_or_reuse_stable_request(root / "d1-projection.json", projection)
        common = {"method_version": projection["runtime_snapshot"]["method_version"], "run_id": envelope.run_id, "go_id": envelope.go_id,
                  "cell_id": envelope.cell_id, "attempt": attempt, "plan_revision": self.binding["plan_revision"],
                  "runtime_revision": snapshot["runtime_revision"], "token_sequence": snapshot["token_sequence"],
                  "checker_role_instance_id": envelope.receiver_role_instance_id, "runtime_projection_path": str(projection_path),
                  "checker_credential_path": self.credential_path("checker"), "state_command": self.state,
                  "transport_command": self.transport, "occurred_at": occurred_at}
        event_id = wc._stable_id(envelope.message_id, "d1-result-v2")
        if recorded["d1_verdict"] == "FAIL":
            native = wc._read_object(source / "ocrv-result.json", "D1 result")
            request = {**common, "schema_version": failed.REQUEST_SCHEMA,
                "post_d1_invocation_id": wc._stable_id(event_id, "normal-fail"), "d1_failure_event_id": event_id,
                "native_attempt_path": str(source), "supervisor_endpoint_path": self.binding["roles"]["supervisor"]["endpoint_path"],
                "escalation_attempt_root": str(root),
                "rework_round": 1 + sum(e.get("event_type") == "REWORK_REQUESTED" and e.get("cell_id") == envelope.cell_id for e in projection["events"]),
                "cell_goal": envelope.payload["cell_goal"], "acceptance_criteria": envelope.payload["d1_criteria"],
                "findings": [json.dumps(f, ensure_ascii=False, sort_keys=True) for f in native["findings"]],
                "reproduction_steps": ["Read the original Checker findings and cited evidence; do not infer a reproduction."],
                "expected_result": "Satisfy the unchanged CELL acceptance criteria.", "evidence_refs": [str(source / "ocrv-result.json")]}
            execute = failed.execute_checker_escalation
        else:
            cells = passed._ordered_cells(projection)
            ids = [c["cell_id"] for c in cells]
            if ids != [c["cell_id"] for c in self.binding["cells"]]:
                raise wc.CompletionError("ROLE_HOST_PLAN_CHANGED", "current required CELL set differs")
            index = ids.index(envelope.cell_id)
            final = index == len(ids) - 1
            target_role = "supervisor" if final else "worker"
            payload = ({"d1_event_id": event_id, "required_cell_ids": ids, "accepted_cell_ids": ids,
                        "final_candidate_message_id": envelope.message_id, "d2_criteria": self.binding["d2_criteria"],
                        "evidence_refs": [str(source / "ocrv-result.json")]} if final else self.binding["cells"][index + 1]["payload"])
            request = {**common, "schema_version": passed.REQUEST_SCHEMA,
                "completion_invocation_id": wc._stable_id(event_id, "normal-pass"), "d1_event_id": event_id,
                "target_cell_id": envelope.cell_id if final else ids[index + 1], "route": "D2_READY" if final else "NEXT_CELL",
                "target_endpoint_path": self.binding["roles"][target_role]["endpoint_path"], "handoff_attempt_root": str(root), "payload": payload}
            execute = passed.execute_checker_completion
        path = wc._write_or_reuse_stable_request(root / "post-d1-request.json", request)
        return execute(request, request_path=path, request_sha256=wc._sha256(path))
