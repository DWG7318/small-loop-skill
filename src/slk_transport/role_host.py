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


def normalized_checker_findings(findings: list[Any]) -> list[str]:
    return [
        json.dumps(_without_provider_thinking(finding), ensure_ascii=False, sort_keys=True)
        for finding in findings
    ]


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
        envelope = Envelope.from_dict(wc._read_object(source / "envelope.json", "source envelope"))
        role = envelope.receiver_role
        if wc._read_object(source / "endpoint.json", "source endpoint") != self.endpoint(role):
            raise wc.CompletionError("ROLE_HOST_BINDING_INVALID", "source receiver is not the prepared role")
        root = source / "role-host"
        root.mkdir(parents=True, exist_ok=True)
        result_path = root / "result.json"
        source_sha256 = self._source_sha256(source, role)
        handoff_evidence = source / "incomplete-handoff" / "evidence.json"
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
        elif envelope.payload_type in {"CANDIDATE_READY", "D1_MANAGEMENT_RETURN"}:
            result = self._checker_result(source, envelope, root, occurred_at, projection)
        else:
            raise wc.CompletionError("ROLE_HOST_OPERATION_INVALID", "no normal suffix for this operation")
        result = {**result, "binding_sha256": self.digest, "source_message_id": envelope.message_id,
                  "source_sha256": source_sha256}
        wc._write_or_reuse_stable_request(result_path, result)
        return result

    def consume_context_terminal(self, source: Path, session_record: Path, session_sha256: str,
                                 *, prepare_only: bool = False) -> dict[str, Any]:
        """Original Checker consumes one proven blocker and keeps the old failed attempt immutable."""
        from . import context_review as cr
        source = source.resolve()
        if wc._read_object(source / 'endpoint.json', 'context Checker endpoint') != self.endpoint('checker'):
            raise ValueError('context consumption is outside the original registered Checker')
        parse_delivery(self.endpoint('checker'), wc._read_object(source / 'envelope.json', 'context source envelope'))
        basis = cr.validate_terminal(source, session_record, session_sha256)
        envelope = basis['envelope']
        root = source / 'role-host/context-terminal'
        seal = {'schema_version': 'slk.ocrv-context-terminal-consumption/v1', 'binding_sha256': self.digest,
                'source_message_id': envelope.message_id, 'source_sha256': basis['source_hashes']}
        receipt = root / 'result.json'
        if receipt.exists():
            value = wc._read_object(receipt, 'context suffix receipt')
            if any(value.get(k) != v for k, v in seal.items()): raise ValueError('context consumption receipt drift')
            return value
        projection = self._boundary(envelope)
        if prepare_only:
            return {**seal, 'status': 'READY_TO_CONSUME_CONTEXT_BLOCKER', 'verdict': 'FAIL',
                    'selected_paths': len(basis['selected']), 'reused_paths': len(basis['reused']),
                    'reviewed_paths': basis['scope'], 'not_reviewed_paths': [p for group in basis['groups'][1:] for p in group]}
        credential = wc.unprotect_dpapi_hex(self.credential_path('checker'))
        try:
            self._authenticate('checker', credential)
        finally:
            credential = ''
        root.mkdir(parents=True, exist_ok=True)
        wc._write_or_reuse_stable_request(root / 'seal.json', seal)
        native = root / 'native-attempt'
        cr.materialize_terminal(source, native, basis)
        # Validate both the immutable source and deterministic derivation again before a formal D1 write.
        refreshed = cr.validate_terminal(source, session_record, session_sha256)
        if refreshed['source_hashes'] != basis['source_hashes']: raise ValueError('context source changed during consumption')
        cr.materialize_terminal(source, native, refreshed)
        occurred_at = datetime.fromtimestamp((source / 'review-segments/segment-001/result.json').stat().st_mtime,
                                             timezone.utc).isoformat()
        suffix = root / 'suffix'; suffix.mkdir(exist_ok=True)
        result = self._checker_result(native, envelope, suffix, occurred_at, projection)
        value = {**result, **seal}
        wc._write_or_reuse_stable_request(receipt, value)
        return value

    def reclassify_completed_checker(self, source: Path) -> dict[str, Any]:
        """Correct one completed OCRV result whose proven blockers were masked by a tool error."""

        from . import checker_escalation as failed

        source = source.resolve()
        endpoint = self.endpoint("checker")
        if wc._read_object(source / "endpoint.json", "source endpoint") != endpoint:
            raise wc.CompletionError(
                "ROLE_HOST_BINDING_INVALID", "classification correction is outside the prepared Checker"
            )
        envelope = Envelope.from_dict(wc._read_object(source / "envelope.json", "source envelope"))
        if envelope.receiver_role != "checker" or envelope.payload_type != "CANDIDATE_READY":
            raise wc.CompletionError(
                "CHECKER_CLASSIFICATION_CORRECTION_INVALID",
                "classification correction requires one completed candidate review",
            )
        prior_receipt = wc._read_object(source / "role-host" / "result.json", "original D1 receipt")
        source_sha256 = self._source_sha256(source, "checker")
        if (
            prior_receipt.get("binding_sha256") != self.digest
            or prior_receipt.get("source_message_id") != envelope.message_id
            or prior_receipt.get("source_sha256") != source_sha256
            or prior_receipt.get("status") != "CHECKER_D1_RECORDED"
            or prior_receipt.get("d1_verdict") != "INCOMPLETE"
            or prior_receipt.get("d1_event_type") != "D1_INCOMPLETE"
        ):
            raise wc.CompletionError(
                "CHECKER_CLASSIFICATION_CORRECTION_INVALID",
                "original RoleHost receipt is not the exact completed INCOMPLETE result",
            )

        original_result_path = source / "ocrv-result.json"
        original_terminal_path = source / "completed.json"
        started_path = source / "started.json"
        original_result = wc._read_object(original_result_path, "original OCRV result")
        original_terminal = wc._read_object(original_terminal_path, "original OCRV terminal")
        raw_path = Path(str(original_result.get("artifacts", {}).get("raw_review", ""))).resolve()
        raw = wc._read_object(raw_path, "original OCRV raw review")
        manifest = raw.get("manifest")
        coverage = manifest.get("coverage") if isinstance(manifest, Mapping) else None
        selected = coverage.get("selected") if isinstance(coverage, Mapping) else None
        completed = coverage.get("completed") if isinstance(coverage, Mapping) else None
        reused = coverage.get("reused", []) if isinstance(coverage, Mapping) else None
        comments = raw.get("comments")
        tools = raw.get("tool_calls")
        severities = [
            str(item.get("severity", "")).strip().upper()
            for item in comments or []
            if isinstance(item, Mapping)
        ]
        blocking = {"MEDIUM", "HIGH", "BLOCKER", "CRITICAL"}
        identity = original_terminal.get("native_identity")
        try:
            validate_native_start(
                started_path,
                adapter=endpoint["adapter"],
                run_id=envelope.run_id,
                cell_id=envelope.cell_id,
                message_id=envelope.message_id,
                request_sha256=envelope.payload_sha256,
            )
        except (OSError, ValueError) as exc:
            raise wc.CompletionError(
                "CHECKER_CLASSIFICATION_CORRECTION_INVALID", "original native start is invalid"
            ) from exc
        if (
            original_result.get("verdict") != "INCOMPLETE"
            or original_result.get("reason_codes") != ["OCR_TOOL_FAILURE"]
            or original_result.get("run_id") != envelope.run_id
            or original_result.get("cell_id") != envelope.cell_id
            or not isinstance(identity, Mapping)
            or original_terminal.get("status") != "completed"
            or identity.get("verdict") != "INCOMPLETE"
            or identity.get("exit_code") != 3
            or raw.get("status") != "complete"
            or raw.get("session_id") != original_result.get("review", {}).get("session_id")
            or not isinstance(manifest, Mapping)
            or manifest.get("terminal_state") != "complete"
            or not isinstance(coverage, Mapping)
            or not isinstance(selected, list)
            or not selected
            or not isinstance(completed, list)
            or not isinstance(reused, list)
            or coverage.get("failed") != []
            or coverage.get("waived") != []
            or {json.dumps(item, sort_keys=True) for item in selected}
            != {json.dumps(item, sort_keys=True) for item in [*completed, *reused]}
            or not isinstance(tools, Mapping)
            or not isinstance(tools.get("failure"), int)
            or tools.get("failure", 0) < 1
            or not isinstance(comments, list)
            or len(severities) != len(comments)
            or any(value not in {"INFO", "LOW", *blocking} for value in severities)
            or not any(value in blocking for value in severities)
            or _without_provider_thinking(comments) != original_result.get("findings")
        ):
            raise wc.CompletionError(
                "CHECKER_CLASSIFICATION_CORRECTION_INVALID",
                "immutable OCRV evidence does not prove a blocker masked only by a tool failure",
            )

        projection = self.projection()
        snapshot = projection.get("runtime_snapshot", {})
        events = projection.get("events", [])
        incomplete = [
            event for event in events
            if isinstance(event, Mapping)
            and event.get("event_type") == "D1_INCOMPLETE"
            and event.get("cell_id") == envelope.cell_id
            and wc._event_details(event).get("candidate_message_id") == envelope.message_id
        ]
        if len(incomplete) != 1:
            raise wc.CompletionError(
                "CHECKER_CLASSIFICATION_CORRECTION_INVALID",
                "current Run does not contain one exact source D1 INCOMPLETE",
            )
        source_event = incomplete[0]
        source_details = wc._event_details(source_event)
        if (
            source_event.get("author_role_instance_id") != endpoint["role_instance_id"]
            or source_details.get("verdict") != "INCOMPLETE"
            or source_details.get("native_terminal_sha256") != wc._sha256(original_terminal_path)
            or source_details.get("native_result_sha256") != wc._sha256(original_result_path)
            or snapshot.get("plan_revision") != self.binding["plan_revision"]
            or snapshot.get("token_holder_role_instance_id") != endpoint["role_instance_id"]
            or snapshot.get("latest_message_id") != envelope.message_id
        ):
            raise wc.CompletionError(
                "CHECKER_CLASSIFICATION_CORRECTION_INVALID",
                "current Checker boundary differs from the immutable incomplete result",
            )

        correction_id = wc._stable_id(str(source_event["event_id"]), "ocr-tool-failure-reclassification")
        correction = source / "role-host" / "classification-correction"
        final_path = source / "role-host" / "classification-correction-result.json"
        if final_path.is_file():
            saved = wc._read_object(final_path, "classification correction result")
            if (
                saved.get("binding_sha256") != self.digest
                or saved.get("source_message_id") != envelope.message_id
                or saved.get("source_sha256") != source_sha256
                or saved.get("correction_id") != correction_id
            ):
                raise wc.CompletionError(
                    "ROLE_HOST_CONFLICT", "classification correction receipt changed identity"
                )
            return saved
        correction.mkdir(parents=True, exist_ok=True)
        for name in ("endpoint.json", "envelope.json", "started.json"):
            destination = correction / name
            if destination.is_file():
                if destination.read_bytes() != (source / name).read_bytes():
                    raise wc.CompletionError(
                        "ROLE_HOST_CONFLICT", "classification correction source changed"
                    )
            else:
                temporary = destination.with_suffix(destination.suffix + ".tmp")
                shutil.copyfile(source / name, temporary)
                temporary.replace(destination)
        corrected_result = {
            **original_result,
            "verdict": "FAIL",
            "reason_codes": ["OCR_BLOCKING_FINDINGS_PRESENT", "OCR_TOOL_FAILURE"],
            "findings": _without_provider_thinking(comments),
        }
        corrected_terminal = {
            **original_terminal,
            "native_identity": {**identity, "verdict": "FAIL", "exit_code": 2},
            "evidence": [
                *[item for item in original_terminal.get("evidence", []) if item != "normalization-correction.json"],
                "normalization-correction.json",
            ],
        }
        corrected_result_path = wc._write_or_reuse_stable_request(
            correction / "ocrv-result.json", corrected_result
        )
        corrected_terminal_path = wc._write_or_reuse_stable_request(
            correction / "completed.json", corrected_terminal
        )
        correction_receipt = {
            "schema_version": "slk.ocrv-classification-correction/v1",
            "cause": "BLOCKING_FINDINGS_PRECEDE_AUXILIARY_TOOL_FAILURE",
            "correction_id": correction_id,
            "source_attempt_path": str(source),
            "source_incomplete_event_id": source_event["event_id"],
            "source_started_sha256": wc._sha256(started_path),
            "source_terminal_sha256": wc._sha256(original_terminal_path),
            "source_result_sha256": wc._sha256(original_result_path),
            "raw_review_path": str(raw_path),
            "raw_review_sha256": wc._sha256(raw_path),
            "corrected_terminal_sha256": wc._sha256(corrected_terminal_path),
            "corrected_result_sha256": wc._sha256(corrected_result_path),
            "reason_codes": corrected_result["reason_codes"],
        }
        wc._write_or_reuse_stable_request(
            correction / "normalization-correction.json", correction_receipt
        )

        corrected_event_id = wc._stable_id(envelope.message_id, "d1-classification-" + correction_id)
        latest_event = snapshot.get("latest_event_id")
        if latest_event == source_event["event_id"]:
            continuation = {
                "run_id": envelope.run_id,
                "go_id": envelope.go_id,
                "cell_id": envelope.cell_id,
                "attempt": source_event["attempt"],
                "plan_revision": self.binding["plan_revision"],
                "checker_endpoint": endpoint,
                "state_command": self.state,
                "occurred_at": datetime.now(timezone.utc).isoformat(),
                "d1_correction_event_id": source_event["event_id"],
                "d1_correction_id": correction_id,
                "d1_correction_kind": "classification",
            }
            recorded = wc._record_checker_d1(
                {"native_attempt_path": str(correction), "candidate_message_id": envelope.message_id},
                continuation,
                checker_credential_path=self.credential_path("checker"),
                timeout_seconds=1,
            )
            if recorded.get("d1_verdict") != "FAIL":
                raise wc.CompletionError(
                    "CHECKER_CLASSIFICATION_CORRECTION_INVALID", "corrected evidence did not record FAIL"
                )
            projection = self.projection()
            snapshot = projection["runtime_snapshot"]
        else:
            matches = [event for event in events if event.get("event_id") == corrected_event_id]
            if len(matches) != 1 or matches[0].get("corrects_event_id") != source_event["event_id"]:
                raise wc.CompletionError(
                    "CHECKER_CLASSIFICATION_CORRECTION_INVALID",
                    "Checker boundary advanced outside the exact correction",
                )

        projection_path = wc._write_or_reuse_stable_request(
            correction / "d1-projection.json", projection
        )
        cell_goal = envelope.payload.get("cell_goal")
        criteria = envelope.payload.get("d1_criteria")
        if not isinstance(cell_goal, str) or not isinstance(criteria, list):
            raise wc.CompletionError(
                "CHECKER_CLASSIFICATION_CORRECTION_INVALID", "candidate acceptance contract is invalid"
            )
        escalation_root = correction / "post-d1"
        escalation_root.mkdir(parents=True, exist_ok=True)
        request_path = correction / "post-d1-request.json"
        saved_request = (
            wc._read_object(request_path, "existing classification escalation request")
            if request_path.is_file() else {}
        )
        request_occurred_at = saved_request.get("occurred_at")
        if not isinstance(request_occurred_at, str) or not request_occurred_at:
            request_occurred_at = datetime.now(timezone.utc).isoformat()
        request = {
            "schema_version": failed.REQUEST_SCHEMA,
            "method_version": snapshot["method_version"],
            "post_d1_invocation_id": wc._stable_id(corrected_event_id, "classification-fail"),
            "run_id": envelope.run_id,
            "go_id": envelope.go_id,
            "cell_id": envelope.cell_id,
            "attempt": source_event["attempt"],
            "plan_revision": self.binding["plan_revision"],
            "runtime_revision": snapshot["runtime_revision"],
            "token_sequence": snapshot["token_sequence"],
            "checker_role_instance_id": endpoint["role_instance_id"],
            "d1_failure_event_id": corrected_event_id,
            "runtime_projection_path": str(projection_path),
            "native_attempt_path": str(correction),
            "supervisor_endpoint_path": self.binding["roles"]["supervisor"]["endpoint_path"],
            "checker_credential_path": self.credential_path("checker"),
            "state_command": self.state,
            "transport_command": self.transport,
            "escalation_attempt_root": str(escalation_root),
            "rework_round": 1 + sum(
                event.get("event_type") == "REWORK_REQUESTED"
                and event.get("cell_id") == envelope.cell_id
                for event in projection["events"]
            ),
            "cell_goal": cell_goal,
            "acceptance_criteria": criteria,
            "findings": normalized_checker_findings(corrected_result["findings"]),
            "reproduction_steps": [
                "Read the preserved Checker findings and cited evidence; do not infer a reproduction."
            ],
            "expected_result": "Satisfy the unchanged CELL acceptance criteria.",
            "evidence_refs": [
                str(corrected_result_path), str(correction / "normalization-correction.json")
            ],
            "occurred_at": request_occurred_at,
        }
        request_path = wc._write_or_reuse_stable_request(request_path, request)
        result = failed.execute_checker_escalation(
            request, request_path=request_path, request_sha256=wc._sha256(request_path)
        )
        receipt = {
            **result,
            "binding_sha256": self.digest,
            "source_message_id": envelope.message_id,
            "source_sha256": source_sha256,
            "correction_id": correction_id,
        }
        wc._write_or_reuse_stable_request(final_path, receipt)
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
        operation = {
            "D1_FAILURE_ESCALATION": "rework",
            "D1_INCOMPLETE_ESCALATION": "management",
            "D2_READY": "d2",
        }.get(envelope.payload_type)
        if (set(result) != {"schema_version", "source_message_id", "operation", "decision"}
            or result.get("schema_version") != "slk.supervisor-result/v1"
            or result.get("source_message_id") != envelope.message_id or operation is None
            or result.get("operation") != operation or not isinstance(result.get("decision"), Mapping)):
            raise wc.CompletionError("SUPERVISOR_RESULT_INVALID", "decision does not bind the native incoming responsibility")
        decision, outgoing = result["decision"], None
        if operation == "rework":
            if envelope.payload.get("rework_round", 0) >= 2:
                raise wc.CompletionError(
                    "ROLE_HOST_CELL_SPLIT_REQUIRED",
                    "the second consecutive formal D1 failure requires a versioned CELL split; the old host cannot issue ordinary rework",
                )
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
        elif operation == "management":
            if (
                set(decision) != {"action", "summary", "evidence_refs"}
                or decision.get("action") not in {
                    "WAIT_FOR_NATIVE_WORK",
                    "ADJUST_CAPACITY",
                    "ADJUST_ENVIRONMENT",
                    "MECHANICAL_RECOVERY",
                }
                or not isinstance(decision.get("summary"), str)
                or not decision["summary"].strip()
            ):
                raise wc.CompletionError(
                    "SUPERVISOR_RESULT_INVALID",
                    "INCOMPLETE management must record one bounded Supervisor action",
                )
            events = []
            if decision["action"] != "WAIT_FOR_NATIVE_WORK":
                checker = self.endpoint("checker")
                return_payload = {
                    "source_d1_incomplete_event_id": envelope.payload["d1_incomplete_event_id"],
                    "candidate_message_id": envelope.payload["candidate_message_id"],
                    "candidate_payload": envelope.payload["candidate_payload"],
                    "candidate_payload_sha256": envelope.payload["candidate_payload_sha256"],
                    "management_action": decision["action"],
                    "management_summary": decision["summary"],
                    "management_evidence_refs": list(decision["evidence_refs"]),
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
                    raise wc.CompletionError(
                        "TEMPORAL_NATIVE_ACK_UNPROVED",
                        "existing native start requires its exact original Temporal request or saved ACK",
                    )
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

    def _resume_checker_failure_suffix(
        self, source: Path, envelope: Envelope, root: Path, occurred_at: str,
        current_projection: Mapping[str, Any], failed: Any, failure_path: Path,
    ) -> dict[str, Any]:
        projection_path = root / "d1-projection.json"
        request_path = root / "post-d1-request.json"
        failure_code = failure_path.stem.removeprefix("failure-")
        try:
            frozen = wc._read_object(projection_path, "frozen D1 projection")
            request = wc._read_object(request_path, "frozen post-D1 request")
            failure = wc._read_object(failure_path, "frozen post-D1 failure")
        except (OSError, ValueError) as exc:
            raise wc.CompletionError(
                "ROLE_HOST_SUFFIX_RECOVERY_INVALID", "frozen Checker suffix evidence is unavailable"
            ) from exc
        expected_failure = {
            "status": "HOST_HANDOFF_FAILED",
            "run_id": envelope.run_id,
            "source_message_id": envelope.message_id,
            "error_code": failure_code,
        }
        management_return = envelope.payload_type == "D1_MANAGEMENT_RETURN"
        candidate_payload = (
            dict(envelope.payload["candidate_payload"])
            if management_return else dict(envelope.payload)
        )
        candidate_message_id = (
            str(envelope.payload["candidate_message_id"])
            if management_return else envelope.message_id
        )
        correction_id = wc._stable_id(envelope.message_id, "management-review") if management_return else None
        event_id = wc._stable_id(
            candidate_message_id,
            f"d1-management-{correction_id}" if management_return else "d1-result-v2",
        )
        snapshot = frozen.get("runtime_snapshot", {})
        try:
            attempt = wc._source_attempt(frozen, envelope)
            native = wc._read_object(source / "ocrv-result.json", "D1 result")
        except (OSError, ValueError) as exc:
            raise wc.CompletionError(
                "ROLE_HOST_SUFFIX_RECOVERY_INVALID", "frozen Checker source identity is invalid"
            ) from exc
        expected_request = {
            "schema_version": failed.REQUEST_SCHEMA,
            "method_version": snapshot.get("method_version"),
            "post_d1_invocation_id": wc._stable_id(event_id, "normal-fail"),
            "run_id": envelope.run_id,
            "go_id": envelope.go_id,
            "cell_id": envelope.cell_id,
            "attempt": attempt,
            "plan_revision": self.binding["plan_revision"],
            "runtime_revision": snapshot.get("runtime_revision"),
            "token_sequence": snapshot.get("token_sequence"),
            "checker_role_instance_id": envelope.receiver_role_instance_id,
            "d1_failure_event_id": event_id,
            "runtime_projection_path": str(projection_path),
            "native_attempt_path": str(source),
            "supervisor_endpoint_path": self.binding["roles"]["supervisor"]["endpoint_path"],
            "checker_credential_path": self.credential_path("checker"),
            "state_command": self.state,
            "transport_command": self.transport,
            "escalation_attempt_root": str(root),
            "rework_round": 1 + sum(
                event.get("event_type") == "REWORK_REQUESTED"
                and event.get("cell_id") == envelope.cell_id
                for event in frozen.get("events", []) if isinstance(event, Mapping)
            ),
            "cell_goal": candidate_payload["cell_goal"],
            "acceptance_criteria": candidate_payload["d1_criteria"],
            "findings": normalized_checker_findings(native["findings"]),
            "reproduction_steps": [
                "Read the original Checker findings and cited evidence; do not infer a reproduction."
            ],
            "expected_result": "Satisfy the unchanged CELL acceptance criteria.",
            "evidence_refs": [str(source / "ocrv-result.json")],
            "occurred_at": occurred_at,
        }
        frozen_snapshot = frozen.get("runtime_snapshot", {})
        current_snapshot = current_projection.get("runtime_snapshot", {})
        boundary_fields = {
            "method_version", "plan_revision", "runtime_revision", "token_sequence",
            "token_holder_role_instance_id", "latest_event_id", "latest_message_id",
        }
        frozen_event = [
            item for item in frozen.get("events", [])
            if isinstance(item, Mapping) and item.get("event_id") == event_id
        ]
        current_event = [
            item for item in current_projection.get("events", [])
            if isinstance(item, Mapping) and item.get("event_id") == event_id
        ]
        if (
            failure != expected_failure
            or request != expected_request
            or any(frozen_snapshot.get(key) != current_snapshot.get(key)
                   for key in boundary_fields - {"runtime_revision", "latest_event_id"})
            or len(frozen_event) != 1
            or current_event != frozen_event
        ):
            raise wc.CompletionError(
                "ROLE_HOST_SUFFIX_RECOVERY_INVALID",
                "frozen Checker suffix no longer matches its current D1 boundary",
            )
        try:
            validated = failed._validate_request(request)
            failed._validate_failure(validated)
            if frozen_snapshot.get("runtime_revision") != current_snapshot.get("runtime_revision"):
                wc._rebind_overwatcher_only_committed_boundary(
                    {**request, "candidate_message_id": envelope.message_id}, frozen,
                    current_projection, current_snapshot.get("runtime_revision"),
                )
            elif frozen_snapshot.get("latest_event_id") != current_snapshot.get("latest_event_id"):
                raise ValueError("current event changed without an authenticated revision")
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise wc.CompletionError(
                "ROLE_HOST_SUFFIX_RECOVERY_INVALID", "frozen Checker suffix validation failed"
            ) from exc
        staged = root / ".checker-post-d1" / str(request["post_d1_invocation_id"])
        delivery = root / str(request["run_id"]) / failed.escalation_message_id(request)
        if failure_code == "CHECKER_ESCALATION_D1_MISMATCH" and (
            any((staged / name).exists() for name in ("endpoint.json", "envelope.json")) or delivery.exists()
        ):
            raise wc.CompletionError(
                "ROLE_HOST_SUFFIX_RECOVERY_INVALID", "Checker escalation was already materialized"
            )
        seal = {
            "schema_version": "slk.role-host-post-d1-suffix-seal/v1",
            "run_id": envelope.run_id,
            "source_message_id": envelope.message_id,
            "binding_sha256": self.digest,
            "runtime_projection_sha256": wc._sha256(projection_path),
            "post_d1_request_sha256": wc._sha256(request_path),
            "failure_sha256": wc._sha256(failure_path),
        }
        try:
            wc._write_or_reuse_stable_request(root / "post-d1-suffix-seal.json", seal)
        except wc.CompletionError as exc:
            raise wc.CompletionError(
                "ROLE_HOST_SUFFIX_RECOVERY_INVALID", "frozen Checker suffix hash changed"
            ) from exc
        if frozen_snapshot.get("runtime_revision") != current_snapshot.get("runtime_revision"):
            refreshed = root / ".checker-post-d1" / str(request["post_d1_invocation_id"]) / (
                "runtime-rebind-" + str(current_snapshot["runtime_revision"])
            )
            refreshed.mkdir(parents=True, exist_ok=True)
            refreshed_projection = wc._write_or_reuse_stable_request(
                refreshed / "projection.json", current_projection
            )
            request = {**request, "runtime_revision": current_snapshot["runtime_revision"],
                       "runtime_projection_path": str(refreshed_projection)}
            request_path = wc._write_or_reuse_stable_request(refreshed / "request.json", request)
        return failed.execute_checker_escalation(
            request, request_path=request_path, request_sha256=wc._sha256(request_path)
        )

    def _checker_result(self, source: Path, envelope: Envelope, root: Path, occurred_at: str,
                        projection: Mapping[str, Any]) -> dict[str, Any]:
        from . import checker_completion as passed, checker_escalation as failed
        from . import checker_management as incomplete

        management_return = envelope.payload_type == "D1_MANAGEMENT_RETURN"
        candidate_payload = (
            dict(envelope.payload["candidate_payload"])
            if management_return else dict(envelope.payload)
        )
        candidate_message_id = (
            str(envelope.payload["candidate_message_id"])
            if management_return else envelope.message_id
        )
        failures = [root / ("failure-" + code + ".json") for code in (
            "CHECKER_ESCALATION_D1_MISMATCH", "CHECKER_ESCALATION_DELIVERY_INVALID",
            "CODEX_DESKTOP_HOST_UNAVAILABLE",
        ) if (root / ("failure-" + code + ".json")).exists()]
        frozen_suffix = (
            root / "d1-projection.json",
            root / "post-d1-request.json",
            *failures,
        )
        if any(path.exists() for path in frozen_suffix):
            if len(failures) != 1 or not all(path.is_file() for path in frozen_suffix):
                raise wc.CompletionError(
                    "ROLE_HOST_SUFFIX_RECOVERY_INVALID", "frozen Checker suffix evidence is incomplete"
                )
            return self._resume_checker_failure_suffix(
                source, envelope, root, occurred_at, projection, failed, failures[0]
            )
        attempt = wc._source_attempt(projection, envelope)
        continuation = {"run_id": envelope.run_id, "go_id": envelope.go_id, "cell_id": envelope.cell_id,
                        "attempt": attempt, "plan_revision": self.binding["plan_revision"],
                        "checker_endpoint": self.endpoint("checker"), "state_command": self.state, "occurred_at": occurred_at}
        if management_return:
            correction_id = wc._stable_id(envelope.message_id, "management-review")
            continuation.update({
                "native_message_id": envelope.message_id,
                "d1_correction_event_id": envelope.payload["source_d1_incomplete_event_id"],
                "d1_correction_id": correction_id,
                "d1_correction_kind": "management",
            })
        recorded = wc._record_checker_d1({"native_attempt_path": str(source), "candidate_message_id": candidate_message_id},
                                        continuation, checker_credential_path=self.credential_path("checker"), timeout_seconds=1)
        projection = self.projection()
        projection_path = wc._write_or_reuse_stable_request(root / "d1-projection.json", projection)
        snapshot = projection["runtime_snapshot"]
        delivery_root = str(Path(self.binding["temporal"]["attempt_root"])) if "temporal" in self.binding else str(root)
        common = {"method_version": snapshot["method_version"], "run_id": envelope.run_id,
                  "go_id": envelope.go_id, "cell_id": envelope.cell_id, "attempt": attempt,
                  "plan_revision": self.binding["plan_revision"],
                  "runtime_revision": snapshot["runtime_revision"],
                  "token_sequence": snapshot["token_sequence"],
                  "checker_role_instance_id": envelope.receiver_role_instance_id,
                  "runtime_projection_path": str(projection_path),
                  "checker_credential_path": self.credential_path("checker"),
                  "state_command": self.state, "transport_command": self.transport,
                  "occurred_at": occurred_at}
        event_id = wc._stable_id(
            candidate_message_id,
            f"d1-management-{correction_id}" if management_return else "d1-result-v2",
        )
        if recorded["d1_verdict"] == "INCOMPLETE":
            matching = [event for event in projection["events"] if event.get("event_id") == event_id]
            if len(matching) != 1:
                raise wc.CompletionError("ROLE_HOST_D1_CHANGED", "current D1 INCOMPLETE is unavailable")
            details = json.loads(matching[0]["details_json"])
            terminal = source / ("completed.json" if (source / "completed.json").is_file() else "failed.json")
            evidence_refs = [str(terminal)]
            if (source / "ocrv-result.json").is_file():
                evidence_refs.append(str(source / "ocrv-result.json"))
            request = {**common, "schema_version": incomplete.REQUEST_SCHEMA,
                "management_invocation_id": wc._stable_id(event_id, "normal-incomplete"),
                "d1_incomplete_event_id": event_id, "native_attempt_path": str(source),
                "supervisor_endpoint_path": self.binding["roles"]["supervisor"]["endpoint_path"],
                "escalation_attempt_root": delivery_root, "reason_codes": list(details["reason_codes"]),
                "evidence_refs": evidence_refs}
            path = wc._write_or_reuse_stable_request(root / "post-d1-request.json", request)
            return incomplete.execute_checker_management(
                request, request_path=path, request_sha256=wc._sha256(path), temporal=self.binding.get("temporal")
            )
        if recorded["d1_verdict"] == "FAIL":
            native = wc._read_object(source / "ocrv-result.json", "D1 result")
            request = {**common, "schema_version": failed.REQUEST_SCHEMA,
                "post_d1_invocation_id": wc._stable_id(event_id, "normal-fail"), "d1_failure_event_id": event_id,
                "native_attempt_path": str(source), "supervisor_endpoint_path": self.binding["roles"]["supervisor"]["endpoint_path"],
                "escalation_attempt_root": delivery_root,
                "rework_round": 1 + sum(e.get("event_type") == "REWORK_REQUESTED" and e.get("cell_id") == envelope.cell_id for e in projection["events"]),
                "cell_goal": candidate_payload["cell_goal"], "acceptance_criteria": candidate_payload["d1_criteria"],
                "findings": normalized_checker_findings(native["findings"]),
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
                        "final_candidate_message_id": candidate_message_id, "d2_criteria": self.binding["d2_criteria"],
                        "evidence_refs": [str(source / "ocrv-result.json")]} if final else self.binding["cells"][index + 1]["payload"])
            request = {**common, "schema_version": passed.REQUEST_SCHEMA,
                "completion_invocation_id": wc._stable_id(event_id, "normal-pass"), "d1_event_id": event_id,
                "target_cell_id": envelope.cell_id if final else ids[index + 1], "route": "D2_READY" if final else "NEXT_CELL",
                "target_endpoint_path": self.binding["roles"][target_role]["endpoint_path"],
                "handoff_attempt_root": delivery_root, "payload": payload}
            execute = passed.execute_checker_completion
        path = wc._write_or_reuse_stable_request(root / "post-d1-request.json", request)
        return execute(request, request_path=path, request_sha256=wc._sha256(path), temporal=self.binding.get("temporal"))
