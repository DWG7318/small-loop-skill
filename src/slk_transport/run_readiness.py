"""Closed, deterministic Run-start readiness evaluation for SLK roles."""

from __future__ import annotations

from . import SUPPORTED_METHOD_VERSIONS

import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any, Mapping


REQUEST_FIELDS = frozenset(
    {
        "schema_version", "run_id", "plan_revision", "roles", "optional_features",
        "bi_open_receipt", "temporal_readiness_receipt", "communication_rehearsal",
    }
)
ADMISSION_FIELDS = frozenset(
    {
        "schema_version", "run_id", "plan_revision", "roles", "optional_features",
        "bi_open_receipt", "temporal_readiness_receipt", "normal_chain_conformance",
        "current_host_binding", "sealed_role_receipts",
    }
)
ROLE_FIELDS = frozenset(
    {
        "role", "role_instance_id",
        "expected_runtime",
        "actual_runtime",
        "expected_model",
        "actual_model",
        "adapter_command",
        "endpoint_path",
        "workspace_root",
        "context_capacity",
        "task_context_estimate",
        "required_skills",
        "required_tools",
        "native_activity_capability",
        "tool_update_status",
    }
)
NATIVE_ACTIVITY_CAPABILITY_FIELDS = frozenset(
    {
        "schema_version",
        "method_version",
        "runtime",
        "read_only_observation",
        "model_call_required",
        "native_events",
    }
)
OPTION_FIELDS = frozenset({"name", "decision", "owner_evidence_ref"})
NORMAL_CHAIN_SOURCE_FIELDS = frozenset(
    {
        "schema_version", "method_version", "status", "source_run_id",
        "plan_revision", "source_state_context", "source_roles",
        "source_communication_rehearsal",
    }
)
SOURCE_STATE_CONTEXT_FIELDS = frozenset({"config_path", "config_sha256"})
SOURCE_ROLE_FIELDS = frozenset(
    {"role", "role_instance_id", "actual_runtime", "endpoint_path", "workspace_root"}
)
REQUIRED_ROLES = ("supervisor", "worker", "checker", "overwatcher")
REQUIRED_OPTIONS = ("Ponytail", "RTK", "Probe CLI")
REQUIRED_REHEARSAL_LEGS = (
    ("SETUP_TO_CHECKER", "supervisor", "checker"),
    ("CELL_TO_WORKER", "checker", "worker"),
    ("CANDIDATE_TO_CHECKER", "worker", "checker"),
    ("D1_FAIL_TO_SUPERVISOR", "checker", "supervisor"),
    ("REWORK_TO_WORKER", "supervisor", "worker"),
    ("D2_READY_TO_SUPERVISOR", "checker", "supervisor"),
    ("ANOMALY_TO_SUPERVISOR", "overwatcher", "supervisor"),
)
SHA256 = frozenset("0123456789abcdef")


def _closed(value: Mapping[str, Any], fields: frozenset[str], label: str) -> None:
    if set(value) != fields:
        raise ValueError(f"{label} must use the exact field set")


def _nonempty(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string")
    return value.strip()


def _string_array(value: Any, label: str) -> list[str]:
    if not isinstance(value, list) or not value or not all(
        isinstance(item, str) and item.strip() for item in value
    ):
        raise ValueError(f"{label} must be a non-empty string array")
    return [item.strip() for item in value]


def _positive_int(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{label} must be a positive integer")
    return value


def _sha256(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and set(value) <= SHA256


def _receipt(path_value: Any) -> Mapping[str, Any] | None:
    if not isinstance(path_value, str) or not path_value.strip():
        return None
    path = Path(path_value)
    if not path.is_absolute() or not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, Mapping) else None


def _valid_bi_receipt(path_value: Any, run_id: str) -> bool:
    value = _receipt(path_value)
    return bool(
        value is not None
        and set(value)
        == {
            "schema_version", "method_version", "run_id", "bi_version", "device_id",
            "visible", "evidence_sha256",
        }
        and value.get("schema_version") == "slk.bi-open-readiness/v1"
        and value.get("method_version") in SUPPORTED_METHOD_VERSIONS
        and value.get("run_id") == run_id
        and value.get("bi_version") == "1.1.0"
        and isinstance(value.get("device_id"), str)
        and bool(str(value.get("device_id")).strip())
        and value.get("visible") is True
        and _sha256(value.get("evidence_sha256"))
    )


def _temporal_binding_from_receipt(path_value: Any, run_id: str) -> dict[str, Any] | None:
    value = _receipt(path_value)
    try:
        if (value is None or set(value) != {
                "schema_version", "method_version", "run_id", "status", "service_mode",
                "workflow_templates", "client_command", "workflow_identity", "attempt_root",
                "evidence_sha256",
            } or value.get("schema_version") != "slk.temporal-readiness/v2"
            or value.get("method_version") != "4.4.2" or value.get("run_id") != run_id
            or value.get("status") != "READY" or value.get("service_mode") != "SHARED_LOCAL"
            or value.get("workflow_templates") != ["SLK.Start", "SLK.Run"]
            or not _sha256(value.get("evidence_sha256"))):
            raise ValueError("Temporal readiness is not closed")
        identity = value["workflow_identity"]
        if not isinstance(identity, Mapping):
            raise ValueError("Temporal identity proof is missing")
        _proof(identity)
        from . import worker_completion as wc
        return wc.validate_temporal_binding({
            "client_command": value["client_command"],
            "workflow_identity_path": identity["path"],
            "workflow_identity_sha256": identity["sha256"],
            "attempt_root": value["attempt_root"],
        }, run_id)
    except (OSError, TypeError, ValueError, KeyError):
        return None


def _valid_temporal_receipt(path_value: Any, run_id: str) -> bool:
    return _temporal_binding_from_receipt(path_value, run_id) is not None


def _proof(reference: Any) -> Mapping[str, Any]:
    """An evidence digest is meaningful only together with its existing bytes."""
    if not isinstance(reference, Mapping) or set(reference) != {"path", "sha256"} or not _sha256(reference["sha256"]):
        raise ValueError("evidence reference is not closed")
    path = Path(reference["path"])
    if not path.is_absolute() or not path.is_file() or path.stat().st_size > 8 * 1024 * 1024:
        raise ValueError("evidence is missing or exceeds the compact receipt limit")
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != reference["sha256"]:
        raise ValueError("evidence bytes changed")
    value = json.loads(raw.decode("utf-8-sig"))
    if not isinstance(value, Mapping):
        raise ValueError("evidence must be an object")
    return value


def _host_has_temporal_binding(host_reference: Any, expected: Mapping[str, Any],
                               run_id: str, revision: int) -> bool:
    from .role_host import RoleHost
    try:
        binding = _proof(host_reference)
        host = RoleHost(binding, host_reference["sha256"])
        return bool(
            binding.get("run_id") == run_id
            and binding.get("plan_revision") == revision
            and host.binding.get("temporal") == dict(expected)
        )
    except (OSError, TypeError, ValueError, KeyError):
        return False


def _rehearsal_has_temporal_binding(path_value: Any, expected: Mapping[str, Any],
                                    run_id: str, revision: int) -> bool:
    value = _receipt(path_value)
    return bool(
        value is not None
        and value.get("run_id") == run_id
        and value.get("plan_revision") == revision
        and _host_has_temporal_binding(value.get("host_binding"), expected, run_id, revision)
    )


def _source_state_config(value: Any) -> str:
    if not isinstance(value, Mapping):
        raise ValueError("source state context must be an object")
    _closed(value, SOURCE_STATE_CONTEXT_FIELDS, "source state context")
    if not _sha256(value["config_sha256"]):
        raise ValueError("source state config hash is invalid")
    path = Path(_nonempty(value["config_path"], "source state config path"))
    if not path.is_absolute() or not path.is_file() or path.stat().st_size > 131072:
        raise ValueError("source state config is unavailable")
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != value["config_sha256"]:
        raise ValueError("source state config changed")
    config = json.loads(raw.decode("utf-8-sig"))
    if (not isinstance(config, Mapping) or set(config) != {"schema_version", "data_root"}
        or config.get("schema_version") != "slk.config/v1"):
        raise ValueError("source state config is invalid")
    data_root = Path(_nonempty(config["data_root"], "source data root"))
    if not data_root.is_absolute() or not data_root.is_dir() or not (data_root / "slk.db").is_file():
        raise ValueError("source state database is unavailable")
    return str(path.resolve())


def _source_roles(value: Any) -> list[Mapping[str, Any]]:
    if not isinstance(value, list) or len(value) != len(REQUIRED_ROLES):
        raise ValueError("source role registry is incomplete")
    roles = []
    for row in value:
        if not isinstance(row, Mapping):
            raise ValueError("source role registry entry is invalid")
        _closed(row, SOURCE_ROLE_FIELDS, "source role registry entry")
        role = _nonempty(row["role"], "source role")
        if role not in REQUIRED_ROLES:
            raise ValueError("source role is unsupported")
        for field in ("role_instance_id", "actual_runtime"):
            _nonempty(row[field], f"source {field}")
        endpoint = Path(_nonempty(row["endpoint_path"], "source endpoint path"))
        workspace = Path(_nonempty(row["workspace_root"], "source workspace root"))
        if not endpoint.is_absolute() or not endpoint.is_file() or not workspace.is_absolute() or not workspace.is_dir():
            raise ValueError("source role path is unavailable")
        roles.append(dict(row))
    if ({row["role"] for row in roles} != set(REQUIRED_ROLES)
        or len({row["role_instance_id"] for row in roles}) != len(roles)):
        raise ValueError("source role identities are incomplete or aliased")
    return roles


def _normal_payload(host: Any, envelope: Any, roles: Mapping[str, Any]) -> None:
    from .adapters.ocrv import OcrvAdapter
    frozen = next((cell for cell in host.binding["cells"]
                   if (cell["go_id"], cell["cell_id"]) == (envelope.go_id, envelope.cell_id)), None)
    if frozen is None:
        raise ValueError("rehearsal CELL is not in the frozen plan")
    task = frozen["payload"]
    goal = _nonempty(task.get("cell_goal", task.get("task")), "frozen CELL goal")
    criteria = _string_array(task.get("d1_criteria"), "frozen D1 criteria")
    kind, payload = envelope.payload_type, envelope.payload
    if kind == "CELL_DISPATCH":
        if payload != {"worker_endpoint": host.endpoint("worker"), "worker_payload": task}:
            raise ValueError("initial dispatch is not the frozen normal dispatch")
    elif kind == "WORKER_TASK":
        if payload != task:
            raise ValueError("Worker did not receive the frozen engineering task")
    elif kind == "CANDIDATE_READY":
        OcrvAdapter()._candidate_request(envelope)
        candidate = payload["candidate"]
        if (payload["cell_goal"] != goal or payload["d1_criteria"] != criteria
            or Path(payload["repository"]).resolve() != Path(roles["worker"]["workspace_root"]).resolve()
            or set(candidate) != {"kind", "commit"} or candidate["kind"] != "commit"
            or not isinstance(candidate["commit"], str) or len(candidate["commit"]) != 40
            or set(candidate["commit"]) - SHA256 or not payload["evidence_files"]):
            raise ValueError("candidate does not bind the frozen engineering scope and evidence")
    elif kind in {"D1_FAILURE_ESCALATION", "D1_REWORK_DIRECTIVE"}:
        if payload["cell_goal"] != goal or payload["acceptance_criteria"] != criteria:
            raise ValueError("failure or rework changed the frozen acceptance")


def _valid_communication_rehearsal(path_value: Any, run_id: str, revision: int,
                                   roles: list[Mapping[str, Any]], *,
                                   state_config_path: str | None = None) -> bool:
    from .contracts import DeliveryResult, parse_delivery
    from .adapters.base import AdapterError
    from .native_activity import validate_native_start
    from .role_host import RoleHost

    value = _receipt(path_value)
    if not (
        value is not None
        and set(value) == {"schema_version", "method_version", "run_id", "plan_revision", "status",
                           "host_binding", "sealed_role_receipts", "legs"}
        and value.get("schema_version") == "slk.communication-rehearsal/v2"
        and value.get("method_version") == "4.4.2"
        and value.get("run_id") == run_id
        and value.get("plan_revision") == revision
        and value.get("status") == "PASS"
        and isinstance(value.get("legs"), list)
        and len(value["legs"]) == len(REQUIRED_REHEARSAL_LEGS)
    ):
        return False
    try:
        registered = {r["role"]: r for r in roles}
        if len({r["role_instance_id"] for r in roles}) != len(roles):
            raise ValueError("role instances must be isolated")
        binding = _proof(value["host_binding"])
        host = RoleHost(binding, value["host_binding"]["sha256"],
                        state_config_path=state_config_path)
        if binding["run_id"] != run_id or binding["plan_revision"] != revision:
            raise ValueError("host scope changed")
        consumers = value["sealed_role_receipts"]
        if not isinstance(consumers, Mapping) or set(consumers) != set(REQUIRED_ROLES):
            raise ValueError("each Run role needs its own saved-consumer evidence")
        for role, reference in consumers.items():
            consumer = _proof(reference)
            if (set(consumer) != {"status", "run_id", "role", "role_instance_id", "sealed_path", "sealed_sha256", "runtime_revision"}
                or consumer["status"] != "SEALED_ROLE_VERIFIED" or consumer["run_id"] != run_id
                or consumer["role"] != role or consumer["role_instance_id"] != registered[role]["role_instance_id"]
                or type(consumer["runtime_revision"]) is not int or consumer["runtime_revision"] < 1):
                raise ValueError("saved consumer evidence changed identity")
            sealed = Path(consumer["sealed_path"])
            if not sealed.is_absolute() or hashlib.sha256(sealed.read_bytes()).hexdigest() != consumer["sealed_sha256"]:
                raise ValueError("saved sealed credential changed")
            if role != "overwatcher":
                endpoint_path = Path(registered[role]["endpoint_path"])
                if (host.endpoint(role) != _receipt(str(endpoint_path))
                    or host.endpoint(role)["role_instance_id"] != registered[role]["role_instance_id"]
                    or Path(host.credential_path(role)).resolve() != sealed.resolve()):
                    raise ValueError("consumer or endpoint is not the prepared binding")
            from . import worker_completion as wc
            secret = wc.unprotect_dpapi_hex(sealed)
            try:
                authenticated = wc._run_json_command(host.state, ["authenticate-role", "--run-id", run_id,
                    "--role-instance-id", registered[role]["role_instance_id"]], credential=secret,
                    state_config_path=state_config_path)
            finally:
                secret = ""
            if (authenticated.get("status") != "authenticated" or authenticated.get("run_id") != run_id
                or authenticated.get("role") != role or authenticated.get("role_instance_id") != registered[role]["role_instance_id"]
                or type(authenticated.get("runtime_revision")) is not int or authenticated["runtime_revision"] < consumer["runtime_revision"]):
                raise ValueError("current saved consumer no longer authenticates its own role")
        seen = set()
        for expected, row in zip(REQUIRED_REHEARSAL_LEGS, value["legs"], strict=True):
            if not isinstance(row, Mapping) or set(row) != {
                "leg_id", "sender_role", "receiver_role", "endpoint", "envelope",
                "sent_receipt", "receiver_started", "commit_request", "commit_result",
            } or tuple(row[k] for k in ("leg_id", "sender_role", "receiver_role")) != expected:
                raise ValueError("normal route evidence is missing or duplicated")
            endpoint, envelope = _proof(row["endpoint"]), _proof(row["envelope"])
            sender, receiver = expected[1:]
            expected_endpoint = host.endpoint(receiver)
            if sender == "overwatcher" and "desktop" in expected_endpoint["address"] and registered[sender]["actual_runtime"] == "codex":
                # This native OW is not a descendant of the Supervisor host.
                # Its own registered caller may differ; the receiver and every
                # other frozen endpoint byte must remain unchanged.
                import copy
                ow_endpoint = _receipt(registered[sender]["endpoint_path"])
                if (ow_endpoint is None or set(ow_endpoint) != {"schema_version", "run_id", "role", "role_instance_id", "agent_runtime", "adapter", "host_id", "endpoint_version", "state", "address"}
                    or ow_endpoint.get("schema_version") != "slk.transport-endpoint/v1"
                    or ow_endpoint.get("run_id") != run_id or ow_endpoint.get("role") != sender
                    or ow_endpoint.get("role_instance_id") != registered[sender]["role_instance_id"]
                    or ow_endpoint.get("agent_runtime") != "codex" or ow_endpoint.get("adapter") != "codex-app-server"
                    or ow_endpoint.get("state") != "active" or ow_endpoint.get("host_id") != expected_endpoint["host_id"]):
                    raise ValueError("native OW caller is not its registered active endpoint")
                caller = ow_endpoint.get("address", {}).get("thread_id")
                if not isinstance(caller, str) or not caller or caller != caller.strip():
                    raise ValueError("native OW Session is missing")
                expected_endpoint = copy.deepcopy(expected_endpoint)
                expected_endpoint["address"]["desktop"]["caller_thread_id"] = caller
            if endpoint != expected_endpoint:
                raise ValueError("rehearsal receiver differs from the current registered endpoint")
            if sender == "overwatcher":
                # OW reports an observation, never sends an engineering TOKEN.
                if (set(envelope) != {"schema_version", "run_id", "event_id", "sender_role_instance_id", "receiver_role_instance_id", "message"}
                    or envelope["schema_version"] != "slk.ow-notification/v1"
                    or not isinstance(envelope["message"], str) or not envelope["message"].startswith("发现异常，请查验")):
                    raise ValueError("OW notification identity is not closed")
                message_id = envelope["event_id"]
                from .contracts import canonical_json_sha256
                payload_sha, cell_id = canonical_json_sha256(envelope), "PREPARATION"
            else:
                parsed = parse_delivery(endpoint, envelope)
                payload_types = {"SETUP_TO_CHECKER": "CELL_DISPATCH", "CELL_TO_WORKER": "WORKER_TASK",
                    "CANDIDATE_TO_CHECKER": "CANDIDATE_READY", "D1_FAIL_TO_SUPERVISOR": "D1_FAILURE_ESCALATION",
                    "REWORK_TO_WORKER": "D1_REWORK_DIRECTIVE", "D2_READY_TO_SUPERVISOR": "D2_READY"}
                if parsed.envelope.payload_type != payload_types[expected[0]]:
                    raise ValueError("echo or recovery does not prove the normal engineering route")
                if (parsed.envelope.sender_role, parsed.envelope.receiver_role) != (sender, receiver):
                    raise ValueError("rehearsal substituted the original sender")
                _normal_payload(host, parsed.envelope, registered)
                message_id, payload_sha, cell_id = parsed.envelope.message_id, parsed.envelope.payload_sha256, parsed.envelope.cell_id
            if (envelope["run_id"] != run_id or envelope["sender_role_instance_id"] != registered[sender]["role_instance_id"]
                or envelope["receiver_role_instance_id"] != registered[receiver]["role_instance_id"] or message_id in seen):
                raise ValueError("rehearsal scope or identity differs")
            seen.add(message_id)
            sent = DeliveryResult.from_dict(_proof(row["sent_receipt"]))
            if sent.status not in {"accepted", "started", "completed"} or sent.run_id != run_id or sent.message_id != message_id or sent.adapter != endpoint["adapter"]:
                raise ValueError("transport receipt is not the exact send")
            _proof(row["receiver_started"])
            validate_native_start(Path(row["receiver_started"]["path"]), adapter=endpoint["adapter"], run_id=run_id,
                                  cell_id=cell_id, message_id=message_id, request_sha256=payload_sha)
            if sender == "overwatcher":
                if row["commit_request"] is not None or row["commit_result"] is not None:
                    raise ValueError("OW cannot commit an engineering TOKEN")
                continue
            commit, result = _proof(row["commit_request"]), _proof(row["commit_result"])
            required = {"run_id": run_id, "go_id": envelope["go_id"], "cell_id": cell_id,
                        "plan_revision": revision, "message_id": message_id, "token_sequence": envelope["token_sequence"],
                        "from_role_instance_id": envelope["sender_role_instance_id"],
                        "to_role_instance_id": envelope["receiver_role_instance_id"], "endpoint_version": endpoint["endpoint_version"],
                        "payload_type": envelope["payload_type"], "payload_sha256": payload_sha}
            if any(commit.get(k) != v for k, v in required.items()):
                raise ValueError("TOKEN commit is not the exact handoff")
            commit_status, committed_message = result.get("status"), result.get("message_id")
            if commit_status == "CHECKER_STARTED":
                # Older host receipts kept the authenticated activation rather
                # than the raw CLI return. Admit only the actual central join;
                # never manufacture a historical committed receipt.
                native = Path(row["receiver_started"]["path"]).parent
                if (set(result) != {"status", "runtime_revision", "token_sequence", "candidate_message_id", "checker_token_already_committed", "native_attempt_path", "binding_sha256", "source_message_id", "source_sha256"}
                    or sender != "worker" or result.get("candidate_message_id") != message_id
                    or result.get("checker_token_already_committed") is not False
                    or result.get("binding_sha256") != value["host_binding"]["sha256"]
                    or Path(result.get("native_attempt_path", "")).resolve() != native.resolve()
                    or not _sha256(result.get("source_sha256")) or not result.get("source_message_id")
                    or not host._committed_delivery(host.projection(), parsed.envelope, native)):
                    raise ValueError("historical activation lacks its live exact central commit")
                commit_status, committed_message = "committed", result["candidate_message_id"]
            evidence = commit.get("start_evidence", {})
            if (evidence.get("sha256") != row["receiver_started"]["sha256"]
                or evidence.get("endpoint_sha256") != row["endpoint"]["sha256"]
                or evidence.get("envelope_sha256") != row["envelope"]["sha256"]
                or evidence.get("message_id") != message_id or evidence.get("native_status") != "STARTED"
                or commit_status not in {"committed", "idempotent_replay"}
                or committed_message != message_id or result.get("token_sequence") != envelope["token_sequence"]
                or type(result.get("runtime_revision")) is not int or result["runtime_revision"] <= commit.get("expected_runtime_revision", 0)):
                raise ValueError("native start or TOKEN result is not proven")
        return True
    except (OSError, TypeError, ValueError, KeyError, AdapterError):
        return False


def _valid_current_registration(host_reference: Any, consumers: Any, run_id: str, revision: int,
                                roles: list[Mapping[str, Any]]) -> bool:
    """Join current Run identity and permission without manufacturing engineering events."""
    from . import worker_completion as wc
    from .role_host import RoleHost
    try:
        registered = {row["role"]: row for row in roles}
        if set(registered) != set(REQUIRED_ROLES) or len({row["role_instance_id"] for row in roles}) != 4:
            raise ValueError("current roles are incomplete or aliased")
        binding = _proof(host_reference)
        host = RoleHost(binding, host_reference["sha256"])
        if binding["run_id"] != run_id or binding["plan_revision"] != revision:
            raise ValueError("current host scope changed")
        if not isinstance(consumers, Mapping) or set(consumers) != set(REQUIRED_ROLES):
            raise ValueError("each current role needs one saved consumer")
        for role, reference in consumers.items():
            consumer = _proof(reference)
            row = registered[role]
            if (set(consumer) != {"status", "run_id", "role", "role_instance_id", "sealed_path", "sealed_sha256", "runtime_revision"}
                or consumer["status"] != "SEALED_ROLE_VERIFIED" or consumer["run_id"] != run_id
                or consumer["role"] != role or consumer["role_instance_id"] != row["role_instance_id"]
                or type(consumer["runtime_revision"]) is not int or consumer["runtime_revision"] < 1):
                raise ValueError("current saved consumer changed identity")
            sealed = Path(consumer["sealed_path"])
            if not sealed.is_absolute() or not sealed.is_file() or wc._sha256(sealed) != consumer["sealed_sha256"]:
                raise ValueError("current sealed credential changed")
            if role != "overwatcher":
                endpoint = _proof({"path": row["endpoint_path"],
                    "sha256": hashlib.sha256(Path(row["endpoint_path"]).read_bytes()).hexdigest()})
                if (host.endpoint(role) != endpoint or endpoint["role_instance_id"] != row["role_instance_id"]
                    or Path(host.credential_path(role)).resolve() != sealed.resolve()):
                    raise ValueError("current endpoint is not the prepared host binding")
            secret = wc.unprotect_dpapi_hex(sealed)
            try:
                authenticated = wc._run_json_command(host.state, ["authenticate-role", "--run-id", run_id,
                    "--role-instance-id", row["role_instance_id"]], credential=secret)
            finally:
                secret = ""
            if (authenticated.get("status") != "authenticated" or authenticated.get("run_id") != run_id
                or authenticated.get("role") != role or authenticated.get("role_instance_id") != row["role_instance_id"]
                or type(authenticated.get("runtime_revision")) is not int
                or authenticated["runtime_revision"] < consumer["runtime_revision"]):
                raise ValueError("current saved consumer is no longer authorized")
        return True
    except (OSError, TypeError, ValueError, KeyError):
        return False


def _valid_current_token_boundary(host_reference: Any, run_id: str, revision: int,
                                  roles: list[Mapping[str, Any]]) -> bool:
    """Prove that the admitted host can resolve the same current boundary it will consume."""
    from . import worker_completion as wc
    from .role_host import RoleHost
    try:
        binding = _proof(host_reference)
        host = RoleHost(binding, host_reference["sha256"])
        projection = host.projection()
        boundary = wc.resolve_authoritative_token_boundary(
            projection, run_id=run_id, plan_revision=revision)
        supervisor = next(row for row in roles if row["role"] == "supervisor")
        return boundary["source"] != "TOKEN_CREATED" or (
            boundary["holder_role_instance_id"] == supervisor["role_instance_id"])
    except (OSError, TypeError, ValueError, KeyError, StopIteration):
        return False


def _normal_chain_conformance(path_value: Any, current_run_id: str) -> str | None:
    value = _receipt(path_value)
    try:
        if value is not None and value.get("schema_version") == "slk.normal-chain-source/v1":
            _closed(value, NORMAL_CHAIN_SOURCE_FIELDS, "normal chain source")
            if (value["method_version"] != "4.4.2" or value["status"] != "PASS"
                or not isinstance(value["source_run_id"], str)
                or value["source_run_id"] == current_run_id):
                raise ValueError("normal chain source scope is invalid")
            revision = _positive_int(value["plan_revision"], "source plan revision")
            state_config_path = _source_state_config(value["source_state_context"])
            roles = _source_roles(value["source_roles"])
            rehearsal = _proof(value["source_communication_rehearsal"])
            if (rehearsal.get("run_id") != value["source_run_id"]
                or not _valid_communication_rehearsal(
                    value["source_communication_rehearsal"]["path"],
                    value["source_run_id"], revision, roles,
                    state_config_path=state_config_path,
                )):
                raise ValueError("normal chain source cannot be recomputed")
            return value["source_run_id"]
        if (value is None or set(value) != {"schema_version", "method_version", "status", "source_run_id",
                "source_readiness_request", "source_communication_rehearsal"}
            or value["schema_version"] != "slk.normal-chain-conformance/v1"
            or value["method_version"] != "4.4.2" or value["status"] != "PASS"
            or not isinstance(value["source_run_id"], str) or value["source_run_id"] == current_run_id):
            raise ValueError("normal-chain conformance scope is invalid")
        source_request = _proof(value["source_readiness_request"])
        source_rehearsal = _proof(value["source_communication_rehearsal"])
        if (set(source_request) != REQUEST_FIELDS
            or source_request["schema_version"] != "slk.run-readiness-request/v1"
            or source_request["run_id"] != value["source_run_id"]
            or Path(source_request["communication_rehearsal"]).resolve()
                != Path(value["source_communication_rehearsal"]["path"]).resolve()
            or source_rehearsal.get("run_id") != value["source_run_id"]
            or not _valid_communication_rehearsal(source_request["communication_rehearsal"],
                source_request["run_id"], source_request["plan_revision"], source_request["roles"])):
            raise ValueError("normal-chain conformance cannot be recomputed")
        return value["source_run_id"]
    except (OSError, TypeError, ValueError, KeyError):
        return None


def _tool_exists(value: str) -> bool:
    candidate = Path(value)
    if candidate.is_absolute() or candidate.parent != Path("."):
        return candidate.is_file()
    return shutil.which(value) is not None


def _workspace_writable(path: Path) -> bool:
    if not path.is_absolute() or not path.is_dir():
        return False
    try:
        descriptor, probe = tempfile.mkstemp(prefix=".slk-readiness-", dir=path)
        os.close(descriptor)
        Path(probe).unlink()
    except OSError:
        return False
    return True


def _enabled_option_entry(name: str, roles: list[Mapping[str, Any]]) -> bool:
    aliases = {"RTK": {"rtk"}, "Probe CLI": {"probe", "probe-cli"}, "Ponytail": {"ponytail"}}[name]
    field = "required_skills" if name == "Ponytail" else "required_tools"
    for role in roles:
        if role["role"] not in {"worker", "checker"}:
            continue
        entries = role[field]
        if not any((Path(entry).stem.casefold() in aliases or
                    (name == "Ponytail" and Path(entry).parent.name.casefold() in aliases))
                   and _tool_exists(entry) for entry in entries):
            return False
    return True


def _native_activity_capability(path_value: Any, runtime: str) -> str | None:
    if not isinstance(path_value, str) or not path_value.strip():
        return "NATIVE_ACTIVITY_CAPABILITY_MISSING"
    path = Path(path_value)
    if not path.is_absolute() or not path.is_file():
        return "NATIVE_ACTIVITY_CAPABILITY_MISSING"
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
        if not isinstance(value, Mapping):
            return "NATIVE_ACTIVITY_CAPABILITY_INVALID"
        _closed(value, NATIVE_ACTIVITY_CAPABILITY_FIELDS, "native activity capability")
        events = value["native_events"]
        if (
            value["schema_version"] != "slk.native-activity-capability/v1"
            or value["method_version"] not in SUPPORTED_METHOD_VERSIONS
            or value["runtime"] != runtime
            or value["read_only_observation"] is not True
            or value["model_call_required"] is not False
            or not isinstance(events, list)
            or not events
            or len(set(events)) != len(events)
            or not all(
                isinstance(item, str) and item and item == item.strip() for item in events
            )
        ):
            return "NATIVE_ACTIVITY_CAPABILITY_INVALID"
    except (OSError, ValueError, json.JSONDecodeError, TypeError):
        return "NATIVE_ACTIVITY_CAPABILITY_INVALID"
    return None


def _role_result(raw: Mapping[str, Any]) -> dict[str, Any]:
    _closed(raw, ROLE_FIELDS, "role")
    role = _nonempty(raw["role"], "role")
    _nonempty(raw["role_instance_id"], "role_instance_id")
    expected_runtime = _nonempty(raw["expected_runtime"], "expected_runtime")
    actual_runtime = _nonempty(raw["actual_runtime"], "actual_runtime")
    expected_model = _nonempty(raw["expected_model"], "expected_model")
    actual_model = _nonempty(raw["actual_model"], "actual_model")
    command = _string_array(raw["adapter_command"], "adapter_command")
    endpoint = Path(_nonempty(raw["endpoint_path"], "endpoint_path"))
    workspace = Path(_nonempty(raw["workspace_root"], "workspace_root"))
    capacity = _positive_int(raw["context_capacity"], "context_capacity")
    estimate = _positive_int(raw["task_context_estimate"], "task_context_estimate")
    skills = _string_array(raw["required_skills"], "required_skills")
    tools = _string_array(raw["required_tools"], "required_tools")
    native_capability = raw["native_activity_capability"]
    tool_update_status = raw["tool_update_status"]

    incompatible: list[str] = []
    repair: list[str] = []
    if actual_runtime != expected_runtime:
        incompatible.append("RUNTIME_MISMATCH")
    if actual_model != expected_model:
        incompatible.append("MODEL_MISMATCH")
    if estimate > capacity:
        incompatible.append("TASK_EXCEEDS_CONTEXT_CAPACITY")
    if not _tool_exists(command[0]):
        repair.append("ADAPTER_COMMAND_MISSING")
    if not endpoint.is_absolute() or not endpoint.is_file():
        repair.append("ENDPOINT_MISSING")
    if not _workspace_writable(workspace):
        repair.append("WORKSPACE_NOT_WRITABLE")
    if any(not Path(item).is_absolute() or not Path(item).is_file() for item in skills):
        repair.append("REQUIRED_SKILL_MISSING")
    if any(not _tool_exists(item) for item in tools):
        repair.append("REQUIRED_TOOL_MISSING")
    if tool_update_status == "UPDATE_REQUIRED":
        repair.append("TOOL_UPDATE_REQUIRED")
    elif tool_update_status != "CURRENT":
        repair.append("TOOL_UPDATE_UNPROVEN")
    if role == "supervisor":
        if native_capability is not None:
            repair.append("NATIVE_ACTIVITY_CAPABILITY_INVALID")
    else:
        native_capability_error = _native_activity_capability(
            native_capability, expected_runtime
        )
        if native_capability_error is not None:
            repair.append(native_capability_error)
    reasons = incompatible or repair
    status = "INCOMPATIBLE" if incompatible else "REPAIR_NEEDED" if repair else "READY"
    return {
        "role": role,
        "status": status,
        "reason_codes": reasons,
        "repair": [f"Restore {role} readiness for {code}." for code in repair],
    }


def evaluate_run_readiness(request: Mapping[str, Any]) -> dict[str, Any]:
    """Evaluate one closed three-role Run request without inferring missing facts."""

    if not isinstance(request, Mapping):
        raise ValueError("request must be an object")
    _closed(request, REQUEST_FIELDS, "request")
    if request["schema_version"] != "slk.run-readiness-request/v1":
        raise ValueError("run readiness schema mismatch")
    run_id = _nonempty(request["run_id"], "run_id")
    revision = _positive_int(request["plan_revision"], "plan_revision")
    raw_roles = request["roles"]
    if not isinstance(raw_roles, list):
        raise ValueError("roles must be an array")
    roles = [_role_result(item) for item in raw_roles if isinstance(item, Mapping)]
    role_names = [item["role"] for item in roles]
    if len(roles) != len(raw_roles) or sorted(role_names) != sorted(REQUIRED_ROLES):
        raise ValueError("roles must contain exactly one supervisor, worker, checker, and overwatcher")

    raw_options = request["optional_features"]
    if not isinstance(raw_options, list):
        raise ValueError("optional_features must be an array")
    options_by_name: dict[str, dict[str, Any]] = {}
    unsupported_option_declared = False
    for raw in raw_options:
        if not isinstance(raw, Mapping):
            raise ValueError("optional feature must be an object")
        _closed(raw, OPTION_FIELDS, "optional feature")
        name = _nonempty(raw["name"], "optional feature name")
        if name in options_by_name:
            raise ValueError("optional feature names must be unique")
        decision = raw["decision"]
        if decision not in {"ON", "OFF", "UNCONFIRMED"}:
            raise ValueError("optional feature decision is invalid")
        evidence = raw["owner_evidence_ref"]
        if not isinstance(evidence, str):
            raise ValueError("owner_evidence_ref must be a string")
        if name not in REQUIRED_OPTIONS:
            unsupported_option_declared = True
            continue
        options_by_name[name] = {
            "name": name,
            "decision": decision,
            "owner_evidence_ref": evidence,
        }

    reason_codes: list[str] = []
    for role in roles:
        for code in role["reason_codes"]:
            if code not in reason_codes:
                reason_codes.append(code)
    if unsupported_option_declared:
        reason_codes.append("OPTION_UNSUPPORTED")
    if not _valid_bi_receipt(request["bi_open_receipt"], run_id):
        reason_codes.append("BI_OPEN_RECEIPT_INVALID")
    temporal_binding = _temporal_binding_from_receipt(request["temporal_readiness_receipt"], run_id)
    if temporal_binding is None:
        reason_codes.append("TEMPORAL_READINESS_INVALID")
    communication_valid = _valid_communication_rehearsal(
        request["communication_rehearsal"], run_id, revision, raw_roles)
    if not communication_valid:
        reason_codes.append("COMMUNICATION_REHEARSAL_INVALID")
    elif temporal_binding is not None and not _rehearsal_has_temporal_binding(
            request["communication_rehearsal"], temporal_binding, run_id, revision):
        reason_codes.append("TEMPORAL_BINDING_INVALID")
    missing = [name for name in REQUIRED_OPTIONS if name not in options_by_name]
    if missing:
        reason_codes.append("REQUIRED_OPTION_MISSING")
    for option in options_by_name.values():
        if option["decision"] == "ON" and not _enabled_option_entry(option["name"], raw_roles):
            if "ENABLED_OPTION_ENTRY_MISSING" not in reason_codes:
                reason_codes.append("ENABLED_OPTION_ENTRY_MISSING")
        if option["decision"] == "UNCONFIRMED" or not option["owner_evidence_ref"].strip():
            if "OPTION_DECISION_REQUIRED" not in reason_codes:
                reason_codes.append("OPTION_DECISION_REQUIRED")
    status = (
        "INCOMPATIBLE"
        if any(item["status"] == "INCOMPATIBLE" for item in roles)
        else "REPAIR_NEEDED"
        if reason_codes
        else "READY"
    )
    canonical = json.dumps(request, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return {
        "schema_version": "slk.run-readiness-result/v1",
        "run_id": run_id,
        "plan_revision": revision,
        "status": status,
        "reason_codes": reason_codes,
        "repairs": [f"Resolve {code}." for code in reason_codes if code != "TASK_EXCEEDS_CONTEXT_CAPACITY"],
        "roles": roles,
        "optional_features": list(options_by_name.values()),
        "request_sha256": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
    }


def evaluate_run_admission(request: Mapping[str, Any]) -> dict[str, Any]:
    """Admit an in-flight Run without replaying a synthetic product failure or D2."""
    if not isinstance(request, Mapping):
        raise ValueError("request must be an object")
    _closed(request, ADMISSION_FIELDS, "admission request")
    if request["schema_version"] != "slk.run-admission-request/v1":
        raise ValueError("Run admission schema mismatch")
    run_id = _nonempty(request["run_id"], "run_id")
    revision = _positive_int(request["plan_revision"], "plan_revision")
    raw_roles = request["roles"]
    if not isinstance(raw_roles, list):
        raise ValueError("roles must be an array")
    roles = [_role_result(item) for item in raw_roles if isinstance(item, Mapping)]
    if len(roles) != len(raw_roles) or sorted(item["role"] for item in roles) != sorted(REQUIRED_ROLES):
        raise ValueError("roles must contain exactly one supervisor, worker, checker, and overwatcher")
    raw_options = request["optional_features"]
    if not isinstance(raw_options, list):
        raise ValueError("optional_features must be an array")
    options_by_name: dict[str, dict[str, Any]] = {}
    unsupported = False
    for raw in raw_options:
        if not isinstance(raw, Mapping):
            raise ValueError("optional feature must be an object")
        _closed(raw, OPTION_FIELDS, "optional feature")
        name = _nonempty(raw["name"], "optional feature name")
        if name in options_by_name:
            raise ValueError("optional feature names must be unique")
        if raw["decision"] not in {"ON", "OFF", "UNCONFIRMED"} or not isinstance(raw["owner_evidence_ref"], str):
            raise ValueError("optional feature decision is invalid")
        if name not in REQUIRED_OPTIONS:
            unsupported = True
        else:
            options_by_name[name] = dict(raw)
    reason_codes: list[str] = []
    for role in roles:
        for code in role["reason_codes"]:
            if code not in reason_codes:
                reason_codes.append(code)
    if unsupported:
        reason_codes.append("OPTION_UNSUPPORTED")
    if not _valid_bi_receipt(request["bi_open_receipt"], run_id):
        reason_codes.append("BI_OPEN_RECEIPT_INVALID")
    temporal_binding = _temporal_binding_from_receipt(request["temporal_readiness_receipt"], run_id)
    if temporal_binding is None:
        reason_codes.append("TEMPORAL_READINESS_INVALID")
    conformance_run_id = _normal_chain_conformance(request["normal_chain_conformance"], run_id)
    if conformance_run_id is None:
        reason_codes.append("NORMAL_CHAIN_CONFORMANCE_INVALID")
    registration_valid = _valid_current_registration(
        request["current_host_binding"], request["sealed_role_receipts"], run_id, revision, raw_roles)
    if not registration_valid:
        reason_codes.append("CURRENT_ROLE_REGISTRATION_INVALID")
    elif temporal_binding is not None and not _host_has_temporal_binding(
            request["current_host_binding"], temporal_binding, run_id, revision):
        reason_codes.append("TEMPORAL_BINDING_INVALID")
    if registration_valid and not _valid_current_token_boundary(
            request["current_host_binding"], run_id, revision, raw_roles):
        reason_codes.append("CURRENT_TOKEN_BOUNDARY_INVALID")
    if any(name not in options_by_name for name in REQUIRED_OPTIONS):
        reason_codes.append("REQUIRED_OPTION_MISSING")
    for option in options_by_name.values():
        if option["decision"] == "ON" and not _enabled_option_entry(option["name"], raw_roles):
            if "ENABLED_OPTION_ENTRY_MISSING" not in reason_codes:
                reason_codes.append("ENABLED_OPTION_ENTRY_MISSING")
        if option["decision"] == "UNCONFIRMED" or not option["owner_evidence_ref"].strip():
            if "OPTION_DECISION_REQUIRED" not in reason_codes:
                reason_codes.append("OPTION_DECISION_REQUIRED")
    status = "INCOMPATIBLE" if any(item["status"] == "INCOMPATIBLE" for item in roles) else (
        "REPAIR_NEEDED" if reason_codes else "READY")
    canonical = json.dumps(request, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return {"schema_version": "slk.run-admission-result/v1", "run_id": run_id,
            "plan_revision": revision, "status": status, "reason_codes": reason_codes,
            "repairs": [f"Resolve {code}." for code in reason_codes], "roles": roles,
            "optional_features": list(options_by_name.values()),
            "conformance_run_id": conformance_run_id,
            "request_sha256": hashlib.sha256(canonical.encode("utf-8")).hexdigest()}
