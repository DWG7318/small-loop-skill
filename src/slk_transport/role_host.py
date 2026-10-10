"""Ordinary transport-job suffixes. No scheduler, Agent, or parallel state store.

The preparation host freezes this local binding. Models receive only their task
and return engineering results; sealed credentials remain in this host process.
"""

from __future__ import annotations

import json
import os
import re
import shutil
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
PROVIDER_THINKING_FIELDS = {"thinking", "reasoning", "analysis"}


def _without_provider_thinking(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            key: _without_provider_thinking(item)
            for key, item in value.items()
            if str(key).lower() not in PROVIDER_THINKING_FIELDS
        }
    if isinstance(value, list):
        return [_without_provider_thinking(item) for item in value]
    return value


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

    def inspect_recovery_authority(self, supervisor_role_instance_id: str) -> dict[str, Any]:
        """Reuse sealed management authority; not a new per-incident Owner approval."""
        if self.endpoint("supervisor")["role_instance_id"] != supervisor_role_instance_id:
            raise ValueError("recovery authority is not the registered Supervisor")
        credential = wc.unprotect_dpapi_hex(self.credential_path("supervisor"))
        try:
            authenticated = self._authenticate("supervisor", credential)
        finally:
            credential = ""
        return {"status": "SUPERVISOR_RECOVERY_AUTHENTICATED", "run_id": self.binding["run_id"],
                "supervisor_role_instance_id": supervisor_role_instance_id,
                "runtime_revision": authenticated["runtime_revision"], "plan_revision": self.binding["plan_revision"]}

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

    @staticmethod
    def _source_sha256(source: Path, role: str) -> str:
        names = (
            ("endpoint.json", "envelope.json", "started.json", "supervisor-result.json")
            if role == "supervisor"
            else (
                "endpoint.json", "envelope.json", "started.json", "completed.json", "failed.json",
                "worker-result.json", "checker-result.json", "ocrv-result.json",
            )
        )
        value: dict[str, str] = {
            name: wc._sha256(source / name) for name in names if (source / name).is_file()
        }
        handoff_evidence = source / "incomplete-handoff" / "evidence.json"
        if handoff_evidence.is_file():
            value["incomplete-handoff/evidence.json"] = wc._sha256(handoff_evidence)
        return canonical_json_sha256(value)

    def _supervisor_start_proof(self, source: Path, envelope: Envelope) -> None:
        endpoint = self.endpoint("supervisor")
        expected_thread = endpoint.get("address", {}).get("thread_id")
        if os.environ.get("CODEX_THREAD_ID") != expected_thread:
            raise wc.CompletionError(
                "ROLE_HOST_SESSION_MISMATCH",
                "Supervisor decision submit must run inside the exact registered Session",
            )
        deadline = time.monotonic() + 10
        while not (source / "started.json").is_file() and time.monotonic() < deadline:
            time.sleep(0.05)
        try:
            parse_delivery(endpoint, wc._read_object(source / "envelope.json", "source envelope"))
            native = validate_native_start(
                source / "started.json",
                adapter=endpoint["adapter"],
                run_id=envelope.run_id,
                cell_id=envelope.cell_id,
                message_id=envelope.message_id,
                request_sha256=envelope.payload_sha256,
            )
            desktop = "desktop" in endpoint.get("address", {})
            expected_kind = "codex-desktop-turn" if desktop else "codex-turn"
            native_id = native["native_task"]["id"]
            if native["native_task"]["kind"] != expected_kind or not native_id.startswith(
                f"{expected_thread}:"
            ):
                raise ValueError("native start differs from the registered Supervisor Session")
        except (OSError, KeyError, TypeError, ValueError) as exc:
            raise wc.CompletionError(
                "ROLE_HOST_START_INVALID",
                "Supervisor decision submit lacks the exact native start proof",
            ) from exc

    def start_d2(self, source: Path) -> dict[str, Any]:
        """Record the original Supervisor's actual start, independently of its verdict."""
        source = source.resolve()
        endpoint = self.endpoint("supervisor")
        envelope = parse_delivery(endpoint, wc._read_object(source / "envelope.json", "D2_READY")).envelope
        if (envelope.payload_type != "D2_READY" or envelope.receiver_role != "supervisor"
            or wc._read_object(source / "endpoint.json", "Supervisor endpoint") != endpoint):
            raise wc.CompletionError("D2_START_INVALID", "D2 start requires the original Supervisor D2_READY")
        self._supervisor_start_proof(source, envelope)
        projection = self._boundary(envelope)
        starts = [event for event in projection.get("events", []) if event.get("event_type") == "TRANSPORT_STARTED"
                  and wc._event_details(event).get("message_id") == envelope.message_id]
        if len(starts) != 1 or any(wc._event_details(starts[0]).get(field) != wc._sha256(source / name)
            for field, name in (("start_evidence_sha256", "started.json"),
                                ("endpoint_sha256", "endpoint.json"), ("envelope_sha256", "envelope.json"))):
            raise wc.CompletionError("D2_START_INVALID", "D2 start requires the exact committed native delivery")
        native = wc._read_object(source / "started.json", "Supervisor native start")
        root = source / "role-host"
        root.mkdir(parents=True, exist_ok=True)
        path = root / "d2_started.json"
        request = {"event_id": wc._stable_id(envelope.message_id, "d2_started"), "run_id": envelope.run_id,
            "go_id": None, "cell_id": None, "attempt": None, "plan_revision": self.binding["plan_revision"],
            "role_instance_id": envelope.receiver_role_instance_id, "event_type": "D2_STARTED",
            "details": {"source_message_id": envelope.message_id, "token_sequence": envelope.token_sequence,
                "native_start_path": str(source / "started.json"), "native_start_sha256": wc._sha256(source / "started.json"),
                "native_task_id": native["native_task"]["id"]},
            "corrects_event_id": None, "occurred_at": datetime.now(timezone.utc).isoformat()}
        if path.is_file():
            request["occurred_at"] = wc._read_object(path, "D2 start")["occurred_at"]
        credential = wc.unprotect_dpapi_hex(self.credential_path("supervisor"))
        try:
            self._authenticate("supervisor", credential)
            wc._write_or_reuse_stable_request(path, request)
            written = self._state_json(["write", "--request", str(path)], credential=credential)
            if written.get("status") != "recorded" or written.get("run_id") != envelope.run_id:
                raise wc.CompletionError("SUPERVISOR_STATE_WRITE_FAILED", "D2 start was not recorded")
        finally:
            credential = ""
        return {"status": "recorded", "run_id": envelope.run_id, "event_id": request["event_id"],
                "occurred_at": request["occurred_at"]}

    def submit_supervisor_decision(self, source: Path) -> dict[str, Any]:
        """Submit one Supervisor decision from its live native Session, before turn end."""
        envelope = Envelope.from_dict(wc._read_object(source / "envelope.json", "source envelope"))
        if envelope.receiver_role != "supervisor" or wc._read_object(
            source / "endpoint.json", "source endpoint"
        ) != self.endpoint("supervisor"):
            raise wc.CompletionError(
                "ROLE_HOST_BINDING_INVALID", "source receiver is not the prepared Supervisor"
            )
        self._supervisor_start_proof(source, envelope)
        root = source / "role-host"
        root.mkdir(parents=True, exist_ok=True)
        result_path = root / "result.json"
        source_sha256 = self._source_sha256(source, "supervisor")
        if result_path.exists():
            saved = wc._read_object(result_path, "owned handoff receipt")
            if (
                saved.get("binding_sha256") != self.digest
                or saved.get("source_message_id") != envelope.message_id
                or saved.get("source_sha256") != source_sha256
            ):
                raise wc.CompletionError(
                    "ROLE_HOST_CONFLICT", "owned handoff receipt changed identity"
                )
            return saved
        decision_path = source / "supervisor-result.json"
        if not decision_path.is_file():
            raise wc.CompletionError(
                "SUPERVISOR_RESULT_INVALID", "Supervisor decision file is missing"
            )
        occurred_at = datetime.fromtimestamp(
            decision_path.stat().st_mtime, timezone.utc
        ).isoformat()
        result = self._supervisor_result(source, envelope, root, occurred_at)
        receipt = {
            **result,
            "binding_sha256": self.digest,
            "source_message_id": envelope.message_id,
            "source_sha256": source_sha256,
        }
        wc._write_or_reuse_stable_request(result_path, receipt)
        return receipt

    def complete(self, source: Path) -> dict[str, Any]:
        """Deliver saved output; never approve its format or infer an engineering action."""
        envelope = Envelope.from_dict(wc._read_object(source / "envelope.json", "source envelope"))
        role = envelope.receiver_role
        if wc._read_object(source / "endpoint.json", "source endpoint") != self.endpoint(role):
            raise wc.CompletionError("ROLE_HOST_BINDING_INVALID", "source receiver is not the prepared role")
        parse_delivery(self.endpoint(role), wc._read_object(source / "envelope.json", "source envelope"))
        root = source / "role-host"
        root.mkdir(parents=True, exist_ok=True)
        if role == "checker" and envelope.payload_type == "CELL_DISPATCH":
            result = wc._read_object(source / "checker-result.json", "Checker dispatch")
            outgoing = self._dispatch_envelope(envelope, result)
            return self._send_owned(root, outgoing, datetime.now(timezone.utc).isoformat(),
                                    self._boundary(envelope))
        legacy_roots = [source / name for name in ("worker-continuation", "invalid-result-supplement",
                        "pre-d0-blocked-recovery", "incomplete-handoff")]
        legacy = next((path for path in legacy_roots if path.exists()), None) if role == "worker" else None
        prior_receipt = root / "result.json"
        if role != "supervisor" and (prior_receipt.is_file() or legacy is not None or (root / "continuation.json").is_file()):
            # A method migration must not replace a previously sent message ID.
            saved = wc._read_object(prior_receipt, "previous handoff receipt") if prior_receipt.is_file() else {}
            if saved and (saved.get("binding_sha256") != self.digest
                or saved.get("source_message_id") != envelope.message_id
                or saved.get("source_sha256") != self._source_sha256(source, role)):
                raise wc.CompletionError("ROLE_HOST_CONFLICT", "previous handoff source identity changed")
            target_role = "checker" if role == "worker" else "supervisor"
            target = self.endpoint(target_role)
            try:
                path = saved.get("native_attempt_path")
                if path is None and role == "worker":
                    attempts = (Path(str(self.binding["temporal"]["attempt_root"])) if "temporal" in self.binding
                                else (legacy or source / "worker-continuation") / "checker-attempts")
                    path = str(attempts / envelope.run_id / wc._stable_id(envelope.message_id, "candidate-ready"))
                if not isinstance(path, str) or not Path(path).is_absolute():
                    raise ValueError("previous receipt has no actual native delivery location")
                native = Path(path)
                old = parse_delivery(wc._read_object(native / "endpoint.json", "previous endpoint"),
                    wc._read_object(native / "envelope.json", "previous envelope")).envelope
                if (wc._read_object(native / "endpoint.json", "previous endpoint") != target
                    or (old.run_id, old.go_id, old.cell_id) != (envelope.run_id, envelope.go_id, envelope.cell_id)
                    or old.sender_role != role or old.sender_role_instance_id != envelope.receiver_role_instance_id):
                    raise ValueError("previous delivery changed scope or prepared receiver")
                from .desktop_current_turn import resolve_delivery_start
                from dataclasses import asdict
                started_path, _ = resolve_delivery_start(native, target, asdict(old))
                delivery = {"status": "started", "message_id": old.message_id,
                            "evidence": str(started_path)}
            except (ValueError, OSError) as exc:
                delivery = {"status": "failed", "error_code": "PREVIOUS_DELIVERY_UNPROVED", "message": str(exc)}
            return {"status": "OUTPUT_DELIVERED" if delivery["status"] == "started"
                    else "OUTPUT_DELIVERY_UNCONFIRMED", "previous_receipt": str(prior_receipt if prior_receipt.exists() else legacy or root / "continuation.json"),
                    "delivery": delivery}
        return self._deliver_output(source, envelope, root)

    def record_worker_action(self, source: Path, event_type: str, details: Mapping[str, Any]) -> dict[str, Any]:
        """Only the live original Worker submits its own existing standard work events."""
        if event_type not in {"WORK_STARTED", "D0_COMPLETED", "CANDIDATE_SUBMITTED"} or not isinstance(details, Mapping):
            raise ValueError("an explicit Worker event and details object are required")
        endpoint = self.endpoint("worker")
        envelope = parse_delivery(endpoint, wc._read_object(source / "envelope.json", "Worker source")).envelope
        if wc._read_object(source / "endpoint.json", "Worker endpoint") != endpoint:
            raise wc.CompletionError("ROLE_HOST_BINDING_INVALID", "Worker endpoint changed")
        context = {"adapter": endpoint["adapter"], "run_id": envelope.run_id,
                   "cell_id": envelope.cell_id, "message_id": envelope.message_id}
        try:
            path = Path(os.environ.get("SLK_NATIVE_ACTIVITY_PATH", ""))
            if (not path.is_absolute() or path.resolve() != (source / "native-activity.json").resolve()
                or json.loads(os.environ.get("SLK_NATIVE_ACTIVITY_CONTEXT", "null")) != context):
                raise ValueError("Worker native invocation differs")
            projection = self._boundary(envelope)  # reuse parent start/atomic-commit synchronization
            native = validate_native_start(source / "started.json", adapter=endpoint["adapter"],
                run_id=envelope.run_id, cell_id=envelope.cell_id, message_id=envelope.message_id,
                request_sha256=envelope.payload_sha256)
            session = endpoint["address"]["session_id"]
            if (native["native_task"]["kind"] != "dsh-session"
                or (session is not None and native["native_task"]["id"] != session)):
                raise ValueError("Worker Session differs")
        except (ValueError, OSError, KeyError, TypeError) as exc:
            raise wc.CompletionError("WORKER_ACTION_CALLER_UNPROVEN", "not the original DSH invocation") from exc
        facts = {"decision_source": "WORKER_EXPLICIT", "source_message_id": envelope.message_id,
                 "native_start_sha256": wc._sha256(source / "started.json"),
                 "native_task_id": native["native_task"]["id"]}
        if event_type == "CANDIDATE_SUBMITTED":
            if not isinstance(details.get("candidate"), Mapping):
                raise ValueError("Worker must explicitly identify its candidate")
            facts["handoff_message_id"] = wc._stable_id(envelope.message_id, "output-delivery")
        if any(key in details and details[key] != value for key, value in facts.items()):
            raise wc.CompletionError("WORKER_ACTION_IDENTITY_MISMATCH", "Worker action changed native source identity")
        root = source / "role-host"
        root.mkdir(parents=True, exist_ok=True)
        path = root / f"worker-{event_type.lower()}.json"
        request = {"event_id": wc._stable_id(envelope.message_id, event_type.lower()),
            "run_id": envelope.run_id, "go_id": envelope.go_id, "cell_id": envelope.cell_id,
            "attempt": wc._source_attempt(projection, envelope), "plan_revision": self.binding["plan_revision"],
            "role_instance_id": endpoint["role_instance_id"], "event_type": event_type,
            "details": {**dict(details), **facts}, "corrects_event_id": None,
            "occurred_at": datetime.now(timezone.utc).isoformat()}
        if path.is_file():
            request["occurred_at"] = wc._read_object(path, "Worker action")["occurred_at"]
        credential = wc.unprotect_dpapi_hex(self.credential_path("worker"))
        try:
            self._authenticate("worker", credential)
            wc._write_or_reuse_stable_request(path, request)
            written = self._state_json(["write", "--request", str(path)], credential=credential)
            if written.get("status") != "recorded":
                raise wc.CompletionError("WORKER_ACTION_WRITE_FAILED", "explicit Worker event was not recorded")
        finally:
            credential = ""
        return {"status": "WORKER_ACTION_RECORDED", "event_type": event_type, "request_path": str(path)}

    def record_checker_decision(self, source: Path, verdict: str, message: str | None = None) -> dict[str, Any]:
        """An explicit original-Checker action; report text never invokes this method."""
        if verdict not in {"PASS", "FAIL", "INCOMPLETE"}:
            raise ValueError("Checker decision must be explicit")
        if message is not None and not isinstance(message, str):
            raise ValueError("Checker message must be original text or absent")
        envelope = Envelope.from_dict(wc._read_object(source / "envelope.json", "source envelope"))
        endpoint = self.endpoint("checker")
        if (envelope.receiver_role != "checker"
            or wc._read_object(source / "endpoint.json", "source endpoint") != endpoint):
            raise wc.CompletionError("ROLE_HOST_BINDING_INVALID", "not the original Checker source")
        parse_delivery(endpoint, wc._read_object(source / "envelope.json", "source envelope"))
        receipt = os.environ.get("SLK_NATIVE_START_RECEIPT", "")
        if not receipt or Path(receipt).resolve() != (source / "native-start.received.json").resolve():
            raise wc.CompletionError("CHECKER_DECISION_CALLER_UNPROVEN", "action is not inside the original OCRV invocation")
        native = validate_native_start(Path(receipt), adapter=endpoint["adapter"],
            run_id=envelope.run_id, cell_id=envelope.cell_id, message_id=envelope.message_id,
            request_sha256=envelope.payload_sha256)
        if native["native_task"]["kind"] != "ocrv-review":
            raise wc.CompletionError("CHECKER_DECISION_CALLER_UNPROVEN", "not an OCRV review")
        root = source / "role-host"
        root.mkdir(parents=True, exist_ok=True)
        decision = {"source_message_id": envelope.message_id, "verdict": verdict,
            "decision_source": "CHECKER_EXPLICIT", "role_instance_id": endpoint["role_instance_id"],
            "native_task_id": native["native_task"]["id"],
            "native_start_path": str(Path(receipt).resolve()), "native_start_sha256": wc._sha256(Path(receipt)),
            "candidate_message_id": (envelope.payload["candidate_message_id"]
                                     if envelope.payload_type == "D1_MANAGEMENT_RETURN" else envelope.message_id),
            "native_message_id": envelope.message_id, "message": message}
        credential = wc.unprotect_dpapi_hex(self.credential_path("checker"))
        try:
            self._authenticate("checker", credential)
            path = root / "checker-decision.json"
            projection = self.projection() if path.is_file() else self._boundary(envelope)
            if path.is_file():
                saved = wc._read_object(path, "explicit Checker decision")
                if set(saved) != set(decision) | {"decided_at"} or any(
                    saved.get(key) != value for key, value in decision.items()
                ):
                    raise wc.CompletionError("ROLE_HOST_CONFLICT", "explicit Checker decision changed")
                decision = saved
            else:
                decision["decided_at"] = datetime.now(timezone.utc).isoformat()
            wc._write_or_reuse_stable_request(path, decision)
            for event_type in ("D1_STARTED", {"PASS":"D1_PASSED", "FAIL":"D1_FAILED", "INCOMPLETE":"D1_INCOMPLETE"}[verdict]):
                request = {"event_id": wc._stable_id(envelope.message_id, event_type.lower()),
                    "run_id": envelope.run_id, "go_id": envelope.go_id, "cell_id": envelope.cell_id,
                    "attempt": wc._source_attempt(projection, envelope),
                    "plan_revision": self.binding["plan_revision"], "role_instance_id": endpoint["role_instance_id"],
                    "event_type": event_type, "details": decision,
                    "corrects_event_id": (envelope.payload["source_d1_incomplete_event_id"]
                                          if envelope.payload_type == "D1_MANAGEMENT_RETURN" and event_type != "D1_STARTED" else None),
                    "occurred_at": str(native["observed_at"] if event_type == "D1_STARTED" else decision["decided_at"])}
                event_path = wc._write_or_reuse_stable_request(root / f"{event_type.lower()}.json", request)
                written = self._state_json(["write", "--request", str(event_path)], credential=credential)
                if written.get("status") != "recorded":
                    raise wc.CompletionError("CHECKER_STATE_WRITE_FAILED", "explicit decision state was not recorded")
        finally:
            credential = ""
        return {"status":"CHECKER_D1_RECORDED", "verdict":verdict, "decision_path":str(path)}

    def submit_checker_decision(self, source: Path, verdict: str, message: str | None = None) -> dict[str, Any]:
        """The original Checker's deliberate call records D1 and runs its existing route."""
        recorded = self.record_checker_decision(source, verdict, message)
        envelope = Envelope.from_dict(wc._read_object(source / "envelope.json", "Checker source"))
        root = source / "role-host" / "checker-handoff"
        projection = self.projection()
        decision = wc._read_object(Path(recorded["decision_path"]), "Checker decision")
        if (root / "envelope.json").is_file():
            outgoing = parse_delivery(wc._read_object(root / "endpoint.json", "Checker target"),
                wc._read_object(root / "envelope.json", "Checker handoff")).envelope
        else:
            from . import checker_completion as completion, checker_escalation as escalation
            from . import checker_management as management
            root.mkdir(parents=True, exist_ok=True)
            runtime = wc._write_or_reuse_stable_request(root / "runtime-projection.json", projection)
            snapshot = projection["runtime_snapshot"]
            frozen = next(c for c in self.binding["cells"] if c["cell_id"] == envelope.cell_id)
            context = frozen["payload"]
            event_type = {"PASS":"D1_PASSED", "FAIL":"D1_FAILED", "INCOMPLETE":"D1_INCOMPLETE"}[verdict]
            event_id = wc._stable_id(envelope.message_id, event_type.lower())
            attempts = (Path(str(self.binding["temporal"]["attempt_root"]))
                        if "temporal" in self.binding else root / "attempts")
            attempts.mkdir(parents=True, exist_ok=True)
            common = {"method_version": projection["summary"]["slk_version"],
                "run_id": envelope.run_id, "go_id": envelope.go_id, "cell_id": envelope.cell_id,
                "attempt": wc._source_attempt(projection, envelope), "plan_revision": self.binding["plan_revision"],
                "runtime_revision": snapshot["runtime_revision"], "token_sequence": snapshot["token_sequence"],
                "checker_role_instance_id": envelope.receiver_role_instance_id,
                "runtime_projection_path": str(runtime), "checker_credential_path": self.credential_path("checker"),
                "state_command": self.state, "transport_command": self.transport,
                "occurred_at": decision["decided_at"]}
            if verdict == "PASS":
                cells = completion._ordered_cells(projection)
                ids = [cell["cell_id"] for cell in cells]
                ordinal = ids.index(envelope.cell_id)
                next_id = ids[ordinal + 1] if ordinal + 1 < len(ids) else None
                route = "NEXT_CELL" if next_id else "D2_READY"
                target = "worker" if next_id else "supervisor"
                payload = (next(c["payload"] for c in self.binding["cells"] if c["cell_id"] == next_id)
                    if next_id else {"d1_event_id": event_id, "required_cell_ids": ids, "accepted_cell_ids": ids,
                        "final_candidate_message_id": decision["candidate_message_id"],
                        "d2_criteria": self.binding["d2_criteria"], "evidence_refs": [recorded["decision_path"]]})
                request = {**common, "schema_version": completion.REQUEST_SCHEMA,
                    "completion_invocation_id": wc._stable_id(envelope.message_id, "explicit-pass"),
                    "target_cell_id": next_id or envelope.cell_id, "d1_event_id": event_id, "route": route,
                    "target_endpoint_path": self.binding["roles"][target]["endpoint_path"],
                    "handoff_attempt_root": str(attempts), "payload": payload}
                completion._validate_request(request)
                prepared = completion._materialize(request, completion._validate_boundary(request))
            else:
                request = {**common, "native_attempt_path": str(source),
                    "supervisor_endpoint_path": self.binding["roles"]["supervisor"]["endpoint_path"],
                    "escalation_attempt_root": str(attempts), "evidence_refs": [recorded["decision_path"]]}
                if verdict == "FAIL":
                    request.update(schema_version=escalation.REQUEST_SCHEMA,
                        post_d1_invocation_id=wc._stable_id(envelope.message_id, "explicit-fail"),
                        d1_failure_event_id=event_id, rework_round=1 + sum(
                            e.get("event_type") == "REWORK_REQUESTED" and e.get("cell_id") == envelope.cell_id
                            for e in projection["events"]),
                        cell_goal=context.get("task", context.get("cell_goal", "")),
                        acceptance_criteria=context["d1_criteria"],
                        findings=[message] if message is not None else [],
                        reproduction_steps=[], expected_result=None)
                    prepared = escalation.materialize_escalation(request)
                else:
                    request.update(schema_version=management.REQUEST_SCHEMA,
                        management_invocation_id=wc._stable_id(envelope.message_id, "explicit-incomplete"),
                        d1_incomplete_event_id=event_id, reason_codes=["CHECKER_EXPLICIT_INCOMPLETE"])
                    prepared = management.materialize_management_escalation(request)
            outgoing = Envelope.from_dict(prepared["envelope"])
        if (outgoing.sender_role != "checker" or outgoing.sender_role_instance_id != envelope.receiver_role_instance_id
            or outgoing.run_id != envelope.run_id or outgoing.go_id != envelope.go_id):
            raise wc.CompletionError("ROLE_HOST_CONFLICT", "Checker action route changed identity")
        handoff = self._send_owned(root, outgoing, decision["decided_at"], projection)
        return {**recorded, "handoff": handoff}

    def _deliver_output(self, source: Path, envelope: Envelope, root: Path) -> dict[str, Any]:
        """Existing transport carries complete files independently of TOKEN/state/ACK."""
        from dataclasses import asdict
        names = ("worker-result.json", "ocrv-result.json", "ocrv-review.json", "checker-receipt.json",
                 "supervisor-result.json", "native.stdout.txt", "native.stderr.txt",
                 "completed.json", "failed.json")
        paths = [source / name for name in names if (source / name).is_file()]
        for directory in ("review-segments", "review-corrections"):
            paths.extend(path for path in (source / directory).rglob("*")
                         if path.is_file() and not path.is_symlink())
        files = [{"path": str(path.resolve()), "bytes": path.stat().st_size,
                  "sha256": wc._sha256(path)} for path in sorted(set(paths))]
        report = {"source_message_id": envelope.message_id, "source_role": envelope.receiver_role,
                  "files": files}
        if envelope.receiver_role == "checker":
            report["input_report"] = dict(envelope.payload)
            report["native_started"] = (source / "started.json").is_file()
        # No output is itself an observable fact, not an invented engineering result.
        report_path = wc._write_or_reuse_stable_request(root / "output.json", report)
        if envelope.receiver_role == "supervisor":
            return {"status": "OUTPUT_SAVED", "report_path": str(report_path)}
        sender = envelope.receiver_role
        credential = wc.unprotect_dpapi_hex(self.credential_path(sender))
        try:
            self._authenticate(sender, credential)
        finally:
            credential = ""
        target_role = "checker" if sender == "worker" else "supervisor"
        target = self.endpoint(target_role)
        payload = report
        kind = "D1_REPORT"
        action = projection = None
        action_error = None
        if sender == "worker":
            frozen = next(c for c in self.binding["cells"] if c["cell_id"] == envelope.cell_id)
            context = frozen["payload"]
            payload = {**report, "repository": self.endpoint("worker")["address"]["cwd"],
                       "cell_goal": context.get("task", context.get("cell_goal", "")),
                       "d1_criteria": context.get("d1_criteria", []),
                       "evidence_files": [row["path"] for row in files]}
            action_path = root / "worker-candidate_submitted.json"
            if action_path.is_file():
                try:
                    submitted = wc._read_object(action_path, "explicit Worker candidate")
                    projection = self.projection()
                    matching = [e for e in projection.get("events", [])
                        if e.get("event_id") == submitted.get("event_id")
                        and e.get("event_type") == "CANDIDATE_SUBMITTED"
                        and e.get("go_id") == envelope.go_id and e.get("cell_id") == envelope.cell_id
                        and e.get("author_role_instance_id") == envelope.receiver_role_instance_id
                        and wc._event_details(e) == submitted.get("details")]
                    details = submitted["details"]
                    if (len(matching) != 1 or submitted.get("attempt") != wc._source_attempt(projection, envelope)
                        or details.get("decision_source") != "WORKER_EXPLICIT"
                        or details.get("source_message_id") != envelope.message_id
                        or details.get("handoff_message_id") != wc._stable_id(envelope.message_id, "output-delivery")
                        or details.get("native_start_sha256") != wc._sha256(source / "started.json")
                        or not isinstance(details.get("candidate"), Mapping)):
                        raise wc.CompletionError("WORKER_ACTION_IDENTITY_MISMATCH", "candidate is not the original Worker's recorded action")
                    action = submitted
                    payload["candidate"] = dict(details["candidate"])
                except (ValueError, OSError, KeyError, TypeError) as exc:
                    action_error = {"status": "failed", "error_code": getattr(exc, "error_code", type(exc).__name__),
                                    "message": str(exc)}
            else:
                # Legacy report locators may be reviewed, but never authorize D0/TOKEN actions.
                try:
                    worker_output = json.loads((source / "worker-result.json").read_bytes())
                except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                    worker_output = None
                if isinstance(worker_output, Mapping):
                    candidate = worker_output.get("candidate")
                    if isinstance(candidate, Mapping) and candidate.get("kind") != "none":
                        payload["candidate"] = dict(candidate)
            payload["candidate_status"] = "PROVIDED" if "candidate" in payload else "NOT_PROVIDED"
            kind = "CANDIDATE_READY" if "candidate" in payload else "WORKER_REPORT"
        outgoing = parse_delivery(target, {
            **asdict(envelope), "message_id": wc._stable_id(envelope.message_id, "output-delivery"),
            "token_sequence": envelope.token_sequence + 1 if action else envelope.token_sequence,
            "sender_role": sender, "sender_role_instance_id": envelope.receiver_role_instance_id,
            "receiver_role": target_role, "receiver_role_instance_id": target["role_instance_id"],
            "receiver_endpoint_version": target["endpoint_version"], "payload_type": kind,
            "payload": payload, "payload_sha256": canonical_json_sha256(payload),
        }).envelope
        target_path = wc._write_or_reuse_stable_request(root / "output-endpoint.json", target)
        envelope_path = wc._write_or_reuse_stable_request(root / "output-envelope.json", asdict(outgoing))
        attempts = ((Path(str(self.binding["temporal"]["attempt_root"])) if "temporal" in self.binding
                     else root / "worker-handoff" / "attempts") if action else root / "output-attempts")
        # dispatch_once provides immutable message de-duplication. No engineering event is written.
        try:
            result = wc._run_json_command(self.transport, ["send", "--endpoint", str(target_path),
                "--envelope", str(envelope_path), "--attempt-root", str(attempts)], credential=None)
        except (ValueError, OSError) as exc:
            result = {"status": "failed", "error_code": getattr(exc, "error_code", type(exc).__name__),
                      "message": str(exc)}
        receipt = {"status": "OUTPUT_DELIVERED" if result.get("status") in {"started", "completed"}
                else "OUTPUT_DELIVERY_UNCONFIRMED", "report_path": str(report_path),
                "message_id": outgoing.message_id, "delivery": dict(result)}
        if action is not None and receipt["status"] == "OUTPUT_DELIVERED":
            try:
                receipt["handoff"] = self._send_owned(root / "worker-handoff", outgoing,
                    action["occurred_at"], projection, register_delivered_output=True)
            except (ValueError, OSError) as exc:
                action_error = {"status": "failed", "error_code": getattr(exc, "error_code", type(exc).__name__),
                                "message": str(exc)}
        if action_error is not None:
            receipt["handoff"] = action_error
        return receipt



    def continue_staged_handoff(
        self,
        source: Path,
        *,
        temporal_request_path: Path | None = None,
        temporal_request_sha256: str | None = None,
    ) -> dict[str, Any]:
        """Start or commit one exact canonical handoff as its original sender."""
        if (temporal_request_path is None) != (temporal_request_sha256 is None):
            raise wc.CompletionError(
                "TEMPORAL_DELIVERY_REQUEST_INVALID",
                "original Temporal request path and hash must be supplied together",
            )
        if "temporal" not in self.binding:
            raise wc.CompletionError(
                "ROLE_HOST_OPERATION_INVALID",
                "staged handoff continuation requires the prepared Temporal binding",
            )
        source = source.resolve()
        envelope_path = source / "envelope.json"
        envelope = Envelope.from_dict(wc._read_object(envelope_path, "staged envelope"))
        expected = (
            Path(str(self.binding["temporal"]["attempt_root"]))
            / envelope.run_id
            / envelope.message_id
        ).resolve()
        if source != expected:
            raise wc.CompletionError(
                "ROLE_HOST_BINDING_INVALID",
                "source is not the exact canonical Temporal attempt",
            )
        endpoint = wc._read_object(source / "endpoint.json", "staged endpoint")
        if endpoint != self.endpoint(envelope.receiver_role):
            raise wc.CompletionError(
                "ROLE_HOST_BINDING_INVALID",
                "staged receiver is not the prepared role",
            )
        parse_delivery(endpoint, wc._read_object(envelope_path, "staged envelope"))
        occurred_at = datetime.fromtimestamp(
            envelope_path.stat().st_mtime, timezone.utc
        ).isoformat()
        return self._send_owned(
            source / "role-host" / "sender-handoff",
            envelope,
            occurred_at,
            self.projection(),
            temporal_request_path=temporal_request_path,
            temporal_request_sha256=temporal_request_sha256,
        )

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

    def _supervisor_result(self, source: Path, envelope: Envelope, root: Path, occurred_at: str) -> dict[str, Any]:
        """Consume the native Supervisor's decision, never derive a verdict."""
        from dataclasses import asdict
        result = wc._read_object(source / "supervisor-result.json", "Supervisor decision")
        operation = {
            "D1_FAILURE_ESCALATION": "rework",
            "D1_INCOMPLETE_ESCALATION": "management",
            "D2_READY": "d2",
        }.get(envelope.payload_type)
        if (result.get("source_message_id", envelope.message_id) != envelope.message_id or operation is None
            or result.get("operation") != operation or not isinstance(result.get("decision"), Mapping)):
            raise wc.CompletionError("SUPERVISOR_ACTION_INVALID", "explicit action does not bind the native incoming responsibility")
        decision, outgoing = result["decision"], None
        if operation == "rework":
            identity_keys = ("d1_failure_event_id", "failed_candidate_sha256", "rework_round")
            if (any(key not in decision or decision[key] != envelope.payload.get(key) for key in identity_keys)
                or not isinstance(decision.get("investigation_mode"), str) or not decision["investigation_mode"].strip()):
                raise wc.CompletionError("SUPERVISOR_ACTION_INVALID", "rework changed the exact failure/candidate identity or omitted explicit intent")
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
        elif operation == "management":
            events = []
            if not isinstance(decision.get("action"), str) or not decision["action"].strip():
                raise wc.CompletionError("SUPERVISOR_ACTION_INVALID", "management requires an explicit action")
            if decision["action"] != "WAIT_FOR_NATIVE_WORK":
                checker = self.endpoint("checker")
                return_payload = {
                    "source_d1_incomplete_event_id": envelope.payload["d1_incomplete_event_id"],
                    "candidate_message_id": envelope.payload["candidate_message_id"],
                    "candidate_payload": envelope.payload["candidate_payload"],
                    "candidate_payload_sha256": envelope.payload["candidate_payload_sha256"],
                    "management_action": decision["action"],
                    "management_summary": decision.get("summary", ""),
                    "management_evidence_refs": decision.get("evidence_refs", []),
                    "review_policy": {
                        "profile": "NORMAL_D1_DEFAULT",
                        "aggregate_budget": "NATIVE_UNLIMITED",
                        "review_timeout": "NATIVE_UNLIMITED",
                        "tool_rounds": "TEMPLATE_DEFAULT",
                    },
                }
                outgoing = parse_delivery(checker, {
                    **asdict(envelope),
                    "message_id": wc._stable_id(envelope.message_id, "supervisor-management-return"),
                    "token_sequence": envelope.token_sequence + 1,
                    "sender_role": "supervisor",
                    "sender_role_instance_id": envelope.receiver_role_instance_id,
                    "receiver_role": "checker",
                    "receiver_role_instance_id": checker["role_instance_id"],
                    "receiver_endpoint_version": checker["endpoint_version"],
                    "payload_type": "D1_MANAGEMENT_RETURN",
                    "payload": return_payload,
                    "payload_sha256": canonical_json_sha256(return_payload),
                }).envelope
        else:
            if decision.get("verdict") not in {"PASS", "FAIL", "INCOMPLETE"}:
                raise wc.CompletionError("SUPERVISOR_ACTION_INVALID", "D2 requires the Supervisor's explicit verdict")
            events = [] if decision["verdict"] == "INCOMPLETE" else [
                ("D2_STARTED", {"source_message_id": envelope.message_id}),
                ("D2_PASSED" if decision["verdict"] == "PASS" else "D2_FAILED", dict(decision))]
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
        if operation == "d2" and (projection.get("runtime_snapshot", {}).get("method_version") == "4.4.3"
            or any(event.get("event_type") == "D2_STARTED"
                   and wc._event_details(event).get("source_message_id") == envelope.message_id
                   and any(key in wc._event_details(event) for key in (
                       "native_start_path", "native_start_sha256", "native_task_id"))
                   for event in projection.get("events", []))):
            starts = [event for event in projection.get("events", []) if event.get("event_type") == "D2_STARTED"
                      and event.get("plan_revision") == self.binding["plan_revision"]
                      and wc._event_details(event).get("source_message_id") == envelope.message_id]
            if len(starts) != 1:
                raise wc.CompletionError("D2_START_REQUIRED", "D2 requires its real recorded start before a final decision")
            start = starts[0]
            if (wc._event_details(start).get("native_start_sha256") != wc._sha256(source / "started.json")
                or wc._timestamp(occurred_at) < wc._timestamp(start["occurred_at"])):
                raise wc.CompletionError("D2_START_INVALID", "D2 result differs from its real start or predates it")
            events = [] if decision["verdict"] == "INCOMPLETE" else [
                ("D2_PASSED" if decision["verdict"] == "PASS" else "D2_FAILED",
                 {**dict(decision), "source_message_id": envelope.message_id, "d2_started_event_id": start["event_id"]})]
        credential = wc.unprotect_dpapi_hex(self.credential_path("supervisor"))
        try:
            self._authenticate("supervisor", credential)
            wc._write_or_reuse_stable_request(root / "supervisor-decision.json", result)
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
            suffix = "rework" if operation == "rework" else "management-return"
            decision_path = source / "supervisor-result.json"
            decision_timing = {
                "decision_prepared_at": datetime.fromtimestamp(
                    decision_path.stat().st_mtime, timezone.utc
                ).isoformat(),
                "decision_submitted_at": datetime.now(timezone.utc).isoformat(),
            }
            return self._send_owned(
                root / suffix,
                outgoing,
                occurred_at,
                self.projection(),
                decision_timing=decision_timing,
            )
        if operation == "management":
            return {"status": "SUPERVISOR_MANAGEMENT_RECORDED", "action": decision["action"]}
        return {"status": "SUPERVISOR_D2_INCOMPLETE" if not events else "SUPERVISOR_D2_RECORDED", "verdict": decision["verdict"]}

    def _send_owned(
        self,
        root: Path,
        envelope: Envelope,
        occurred_at: str,
        projection: Mapping[str, Any],
        *,
        temporal_request_path: Path | None = None,
        temporal_request_sha256: str | None = None,
        decision_timing: Mapping[str, str] | None = None,
        register_delivered_output: bool = False,
    ) -> dict[str, Any]:
        from dataclasses import asdict
        if decision_timing is not None:
            if set(decision_timing) != {"decision_prepared_at", "decision_submitted_at"}:
                raise wc.CompletionError(
                    "ROLE_HOST_TIMELINE_INVALID", "Supervisor decision timing is not closed"
                )
            try:
                timestamps = [
                    datetime.fromisoformat(decision_timing[name].replace("Z", "+00:00"))
                    for name in ("decision_prepared_at", "decision_submitted_at")
                ]
            except (AttributeError, TypeError, ValueError) as exc:
                raise wc.CompletionError(
                    "ROLE_HOST_TIMELINE_INVALID", "Supervisor decision timing is not RFC3339"
                ) from exc
            if any(value.tzinfo is None for value in timestamps) or timestamps[1] < timestamps[0]:
                raise wc.CompletionError(
                    "ROLE_HOST_TIMELINE_INVALID", "Supervisor decision timing is not ordered"
                )
        target = self.endpoint(envelope.receiver_role)
        sender = self.endpoint(envelope.sender_role)
        if decision_timing is not None and envelope.sender_role != "supervisor":
            raise wc.CompletionError(
                "ROLE_HOST_TIMELINE_INVALID", "only a Supervisor decision can use decision timing"
            )
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
            if temporal_request_path is not None and temporal_request_sha256 is not None:
                native = wc.acknowledge_temporal_delivery(
                    self.binding["temporal"], root, target, asdict(envelope),
                    request_path=temporal_request_path,
                    request_sha256=temporal_request_sha256,
                    attempt=attempt_number,
                    required_attempt_root=attempts,
                )
            elif not (native / "started.json").is_file():
                native = wc.start_temporal_delivery(
                    self.binding["temporal"], root, target, asdict(envelope),
                    attempt=attempt_number, source_runtime_revision=revision,
                    required_attempt_root=attempts,
                )
            else:
                operation_id = wc._stable_id(envelope.message_id, "temporal-delivery")
                if not wc._temporal_ack_recorded(
                    root, operation_id=operation_id,
                    run_id=envelope.run_id, message_id=envelope.message_id,
                ):
                    if not register_delivered_output:
                        raise wc.CompletionError(
                            "TEMPORAL_NATIVE_ACK_UNPROVED",
                            "existing native start requires its exact original Temporal request or saved ACK",
                        )
                    from .desktop_current_turn import resolve_delivery_start
                    resolve_delivery_start(native, target, asdict(envelope))
                    if (wc._read_object(native / "endpoint.json", "delivered endpoint") != target
                        or wc._read_object(native / "envelope.json", "delivered envelope") != asdict(envelope)):
                        raise wc.CompletionError("ROLE_HOST_START_INVALID", "delivered output identity differs")
                    native = wc.start_temporal_delivery(self.binding["temporal"], root, target, asdict(envelope),
                        attempt=attempt_number, source_runtime_revision=revision, required_attempt_root=attempts)
        elif not native.exists():
            wc._run_json_command(self.transport, ["send", "--endpoint", str(endpoint_path), "--envelope", str(envelope_path),
                                                  "--attempt-root", str(attempts)], credential=None)
        from .desktop_current_turn import resolve_delivery_start
        started_path, native_start = resolve_delivery_start(native, target, asdict(envelope))
        receiver_started_at = native_start["observed_at"]
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
                "payload_sha256": envelope.payload_sha256, "occurred_at": receiver_started_at,
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
            if value.get("status") == "error":
                code, message = value.get("code"), value.get("message")
                sensitive = json.dumps({"code": code, "message": message}, ensure_ascii=False).lower()
                if (isinstance(code, str) and re.fullmatch(r"[A-Z][A-Z0-9_]{2,95}", code)
                    and isinstance(message, str) and message.strip() == message and 0 < len(message) <= 512
                    and not any(term in sensitive for term in ("credential", "secret", "password", "api_key"))):
                    raise wc.CompletionError(code, message)
            if (value.get("status") not in {"committed", "idempotent_replay"}
                or value.get("message_id") != envelope.message_id or value.get("run_id") != envelope.run_id
                or type(value.get("runtime_revision")) is not int or value["runtime_revision"] != auth["runtime_revision"] + 1
                or value.get("token_sequence") != envelope.token_sequence
                or value.get("token_owner_role_instance_id") != envelope.receiver_role_instance_id):
                raise wc.CompletionError("ROLE_HOST_COMMIT_FAILED", "owned handoff commit did not match")
            result_path = wc._write_or_reuse_stable_request(path.with_suffix(".result.json"), value)
            if decision_timing is not None:
                timeline = {
                    "schema_version": "slk.role-host-handoff-timeline/v1",
                    "run_id": envelope.run_id,
                    "message_id": envelope.message_id,
                    **dict(decision_timing),
                    "receiver_started_at": receiver_started_at,
                    "central_transport_occurred_at": receiver_started_at,
                    "committed_at": datetime.fromtimestamp(
                        result_path.stat().st_mtime, timezone.utc
                    ).isoformat(),
                }
                wc._write_or_reuse_stable_request(root / "handoff-timeline.json", timeline)
            return {"status": "OWNED_HANDOFF_COMMITTED", "message_id": envelope.message_id, "commit_path": str(path)}
        finally:
            credential = ""

    @staticmethod
    def _outgoing_attempt(envelope: Envelope, projection: Mapping[str, Any]) -> int:
        if envelope.payload_type != "D1_REWORK_DIRECTIVE":
            references = {envelope.payload[key] for key in ("d1_failure_event_id", "d1_incomplete_event_id", "d1_event_id",
                                                           "source_d1_incomplete_event_id")
                          if isinstance(envelope.payload.get(key), str)}
            source_id = envelope.payload.get("source_message_id")
            matches = []
            for event in projection.get("events", []):
                if event.get("go_id") != envelope.go_id or event.get("cell_id") != envelope.cell_id:
                    continue
                details = wc._event_details(event) or {}
                if ((references and event.get("event_id") in references)
                    or (source_id is not None and event.get("event_type") == "TRANSPORT_STARTED"
                        and details.get("message_id") == source_id)):
                    matches.append(event.get("attempt"))
            if references or source_id is not None:
                if len(matches) != 1 or type(matches[0]) is not int or matches[0] < 1:
                    raise wc.CompletionError("ROLE_HOST_ATTEMPT_UNPROVEN", "handoff must bind its exact original engineering attempt")
                return matches[0]
            return 1
        matches = []
        for event in projection.get("events", []):
            if (event.get("event_type") != "REWORK_REQUESTED" or event.get("cell_id") != envelope.cell_id
                or event.get("go_id") != envelope.go_id):
                continue
            details = wc._event_details(event)
            if details and all(details.get(k) == envelope.payload.get(k) for k in (
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
            or event.get("attempt") != self._outgoing_attempt(envelope, projection)
            or event.get("corrects_event_id") is not None):
            raise wc.CompletionError("ROLE_HOST_CONFLICT", "central handoff changed scope or role")
        try:
            from .desktop_current_turn import resolve_delivery_start
            start_path, _ = resolve_delivery_start(native, self.endpoint(envelope.receiver_role), asdict(envelope))
            exact = (wc._read_object(native / "endpoint.json", "committed endpoint") == self.endpoint(envelope.receiver_role)
                and wc._read_object(native / "envelope.json", "committed envelope") == asdict(envelope)
                and details.get("start_evidence_sha256") == wc._sha256(start_path)
                and all(details.get(key) == wc._sha256(native / name) for key, name in (
                    ("endpoint_sha256", "endpoint.json"),
                    ("envelope_sha256", "envelope.json"))))
        except (OSError, ValueError) as exc:
            raise wc.CompletionError("ROLE_HOST_CONFLICT", "committed native evidence is unavailable") from exc
        if not exact:
            raise wc.CompletionError("ROLE_HOST_CONFLICT", "committed native evidence changed")
        return True
