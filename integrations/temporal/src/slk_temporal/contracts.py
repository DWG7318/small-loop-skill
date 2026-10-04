"""Closed, deterministic contracts shared by the two SLK Temporal templates."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, Mapping


IDENTIFIER = re.compile(r"^[A-Za-z0-9_.-]{1,128}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
ENGINEERING_ROLES = ("SUPERVISOR", "CHECKER", "WORKER")
ALL_ROLES = frozenset((*ENGINEERING_ROLES, "OVERWATCHER"))


class ContractError(ValueError):
    """Raised when a Temporal template input is not a closed SLK contract."""


def _closed(value: object, fields: set[str], label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != fields:
        raise ContractError(f"{label} must use the exact field set")
    return value


def _identifier(value: object, label: str) -> str:
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
        raise ContractError(f"{label} must be a canonical identifier")
    return value


def _hash(value: object, label: str) -> str:
    if not isinstance(value, str) or not SHA256.fullmatch(value):
        raise ContractError(f"{label} must be a lowercase SHA-256")
    return value


def _integer(value: object, label: str, *, minimum: int = 0, maximum: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ContractError(f"{label} must be an integer >= {minimum}")
    if maximum is not None and value > maximum:
        raise ContractError(f"{label} must be an integer <= {maximum}")
    return value


@dataclass(frozen=True)
class RoleBinding:
    role: str
    role_instance_id: str
    endpoint_ref: str

    @classmethod
    def from_dict(cls, value: object) -> "RoleBinding":
        source = _closed(value, {"role", "role_instance_id", "endpoint_ref"}, "role binding")
        role = source["role"]
        if role not in ALL_ROLES:
            raise ContractError("role binding role is not an SLK role")
        return cls(
            role=role,
            role_instance_id=_identifier(source["role_instance_id"], "role_instance_id"),
            endpoint_ref=_identifier(source["endpoint_ref"], "endpoint_ref"),
        )

    def to_dict(self) -> dict[str, str]:
        return {
            "role": self.role,
            "role_instance_id": self.role_instance_id,
            "endpoint_ref": self.endpoint_ref,
        }


@dataclass(frozen=True)
class StartSlkRequest:
    run_id: str
    method_version: str
    runtime_revision: int
    task_queue: str
    ack_timeout_seconds: int
    startup_idempotency_key: str
    roles: tuple[RoleBinding, ...]

    @classmethod
    def from_dict(cls, value: object) -> "StartSlkRequest":
        fields = {
            "run_id",
            "method_version",
            "runtime_revision",
            "task_queue",
            "ack_timeout_seconds",
            "startup_idempotency_key",
            "roles",
        }
        source = _closed(value, fields, "SLK startup request")
        if source["method_version"] != "4.4.0":
            raise ContractError("method_version must be 4.4.0")
        raw_roles = source["roles"]
        if not isinstance(raw_roles, list):
            raise ContractError("roles must be an array")
        roles = tuple(RoleBinding.from_dict(item) for item in raw_roles)
        counts = {role: sum(item.role == role for item in roles) for role in ALL_ROLES}
        if any(counts[role] != 1 for role in ALL_ROLES):
            raise ContractError(
                "roles must contain exactly one SUPERVISOR, CHECKER, WORKER and OVERWATCHER"
            )
        identities = [item.role_instance_id for item in roles]
        endpoints = [item.endpoint_ref for item in roles]
        if len(set(identities)) != len(identities):
            raise ContractError("role_instance_id must be unique")
        if len(set(endpoints)) != len(endpoints):
            raise ContractError("endpoint_ref must be unique")
        return cls(
            run_id=_identifier(source["run_id"], "run_id"),
            method_version="4.4.0",
            runtime_revision=_integer(source["runtime_revision"], "runtime_revision"),
            task_queue=_identifier(source["task_queue"], "task_queue"),
            ack_timeout_seconds=_integer(
                source["ack_timeout_seconds"], "ack_timeout_seconds", minimum=1, maximum=3600
            ),
            startup_idempotency_key=_identifier(
                source["startup_idempotency_key"], "startup_idempotency_key"
            ),
            roles=roles,
        )

    @property
    def overwatcher(self) -> RoleBinding | None:
        return next((item for item in self.roles if item.role == "OVERWATCHER"), None)

    @property
    def supervisor(self) -> RoleBinding:
        return next(item for item in self.roles if item.role == "SUPERVISOR")

    @property
    def startup_fingerprint(self) -> str:
        encoded = json.dumps(
            self.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def to_dict(self) -> dict[str, object]:
        return {
            "run_id": self.run_id,
            "method_version": self.method_version,
            "runtime_revision": self.runtime_revision,
            "task_queue": self.task_queue,
            "ack_timeout_seconds": self.ack_timeout_seconds,
            "startup_idempotency_key": self.startup_idempotency_key,
            "roles": [item.to_dict() for item in self.roles],
        }


@dataclass(frozen=True)
class DeliveryRequest:
    operation_id: str
    run_id: str
    cell_id: str
    attempt: int
    message_id: str
    sender_role_instance_id: str
    receiver_role_instance_id: str
    payload_sha256: str
    source_runtime_revision: int

    @classmethod
    def from_dict(cls, value: object) -> "DeliveryRequest":
        fields = {
            "operation_id",
            "run_id",
            "cell_id",
            "attempt",
            "message_id",
            "sender_role_instance_id",
            "receiver_role_instance_id",
            "payload_sha256",
            "source_runtime_revision",
        }
        source = _closed(value, fields, "delivery request")
        return cls(
            operation_id=_identifier(source["operation_id"], "operation_id"),
            run_id=_identifier(source["run_id"], "run_id"),
            cell_id=_identifier(source["cell_id"], "cell_id"),
            attempt=_integer(source["attempt"], "attempt", minimum=1),
            message_id=_identifier(source["message_id"], "message_id"),
            sender_role_instance_id=_identifier(
                source["sender_role_instance_id"], "sender_role_instance_id"
            ),
            receiver_role_instance_id=_identifier(
                source["receiver_role_instance_id"], "receiver_role_instance_id"
            ),
            payload_sha256=_hash(source["payload_sha256"], "payload_sha256"),
            source_runtime_revision=_integer(
                source["source_runtime_revision"], "source_runtime_revision"
            ),
        )

    def to_dict(self) -> dict[str, object]:
        return self.__dict__.copy()


@dataclass(frozen=True)
class NativeStartAck:
    operation_id: str
    message_id: str
    receiver_role_instance_id: str
    payload_sha256: str
    started_receipt_sha256: str

    @classmethod
    def from_dict(cls, value: object) -> "NativeStartAck":
        fields = {
            "operation_id",
            "message_id",
            "receiver_role_instance_id",
            "payload_sha256",
            "started_receipt_sha256",
        }
        source = _closed(value, fields, "native start acknowledgement")
        return cls(
            operation_id=_identifier(source["operation_id"], "operation_id"),
            message_id=_identifier(source["message_id"], "message_id"),
            receiver_role_instance_id=_identifier(
                source["receiver_role_instance_id"], "receiver_role_instance_id"
            ),
            payload_sha256=_hash(source["payload_sha256"], "payload_sha256"),
            started_receipt_sha256=_hash(
                source["started_receipt_sha256"], "started_receipt_sha256"
            ),
        )

    def require_match(self, delivery: DeliveryRequest) -> None:
        expected = (
            delivery.operation_id,
            delivery.message_id,
            delivery.receiver_role_instance_id,
            delivery.payload_sha256,
        )
        actual = (
            self.operation_id,
            self.message_id,
            self.receiver_role_instance_id,
            self.payload_sha256,
        )
        if actual != expected:
            raise ContractError("native start acknowledgement does not match the delivery")

    def to_dict(self) -> dict[str, str]:
        return self.__dict__.copy()


@dataclass(frozen=True)
class OverwatcherExitNotice:
    event_id: str
    run_id: str
    overwatcher_role_instance_id: str
    requested_by_role_instance_id: str
    evidence_sha256: str

    @classmethod
    def from_dict(cls, value: object) -> "OverwatcherExitNotice":
        fields = {
            "event_id",
            "run_id",
            "overwatcher_role_instance_id",
            "requested_by_role_instance_id",
            "evidence_sha256",
        }
        source = _closed(value, fields, "Overwatcher exit notice")
        return cls(
            event_id=_identifier(source["event_id"], "event_id"),
            run_id=_identifier(source["run_id"], "run_id"),
            overwatcher_role_instance_id=_identifier(
                source["overwatcher_role_instance_id"], "overwatcher_role_instance_id"
            ),
            requested_by_role_instance_id=_identifier(
                source["requested_by_role_instance_id"], "requested_by_role_instance_id"
            ),
            evidence_sha256=_hash(source["evidence_sha256"], "evidence_sha256"),
        )


@dataclass(frozen=True)
class RuntimeGuardResolution:
    event_id: str
    run_id: str
    supervisor_role_instance_id: str
    blocker_event_id: str
    resolution: str
    evidence_sha256: str

    @classmethod
    def from_dict(cls, value: object) -> "RuntimeGuardResolution":
        fields = {
            "event_id",
            "run_id",
            "supervisor_role_instance_id",
            "blocker_event_id",
            "resolution",
            "evidence_sha256",
        }
        source = _closed(value, fields, "runtime guard resolution")
        if source["resolution"] != "OVERWATCHER_RESTORED":
            raise ContractError("runtime guard resolution must prove OVERWATCHER_RESTORED")
        return cls(
            event_id=_identifier(source["event_id"], "event_id"),
            run_id=_identifier(source["run_id"], "run_id"),
            supervisor_role_instance_id=_identifier(
                source["supervisor_role_instance_id"], "supervisor_role_instance_id"
            ),
            blocker_event_id=_identifier(source["blocker_event_id"], "blocker_event_id"),
            resolution="OVERWATCHER_RESTORED",
            evidence_sha256=_hash(source["evidence_sha256"], "evidence_sha256"),
        )
