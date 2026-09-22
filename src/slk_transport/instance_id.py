"""Deterministic bounded native identity for the one SLK Worker."""

from __future__ import annotations

import hashlib
import re


MAX_INSTANCE_ID = 64


def _normalized(run_id: str) -> str:
    if not isinstance(run_id, str) or not run_id.strip():
        raise ValueError("run_id must be non-empty")
    value = re.sub(r"[^A-Za-z0-9_.-]+", "-", run_id.strip()).strip("-._")
    if not value:
        raise ValueError("run_id has no usable identity characters")
    return value


def expected_worker_instance_id(run_id: str) -> str:
    normalized = _normalized(run_id)
    ordinary = f"{normalized}-worker"
    if len(ordinary) <= MAX_INSTANCE_ID:
        return ordinary
    digest = hashlib.sha256(run_id.encode("utf-8")).hexdigest()[:12]
    prefix_length = MAX_INSTANCE_ID - len("-worker-") - len(digest)
    prefix = normalized[:prefix_length].rstrip("-._")
    if not prefix:
        raise ValueError("run_id cannot produce a bounded Worker identity")
    return f"{prefix}-worker-{digest}"


def validate_worker_instance_id(run_id: str, instance_id: str) -> None:
    expected = expected_worker_instance_id(run_id)
    if instance_id != expected or len(instance_id) > MAX_INSTANCE_ID:
        raise ValueError(f"instance_id must equal deterministic Worker identity {expected}")
