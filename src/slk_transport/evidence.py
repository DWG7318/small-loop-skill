"""Immutable, message-scoped evidence for SLK transport attempts."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from .contracts import Envelope


class EvidenceError(RuntimeError):
    """Raised when transport evidence cannot be safely created."""


def _evidence_name(value: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value in {".", ".."}
        or Path(value).name != value
        or "/" in value
        or "\\" in value
    ):
        raise EvidenceError("evidence name must be one safe file name")
    return value


@dataclass(frozen=True)
class Attempt:
    root: Path

    def write_text_once(self, name: str, text: str) -> Path:
        safe_name = _evidence_name(name)
        if not isinstance(text, str):
            raise EvidenceError("evidence text must be a string")
        destination = self.root / safe_name
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{safe_name}.",
            suffix=".tmp",
            dir=self.root,
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
                stream.write(text)
                stream.flush()
                os.fsync(stream.fileno())
            try:
                os.link(temporary, destination)
            except FileExistsError as exc:
                raise EvidenceError(f"evidence already exists: {safe_name}") from exc
            return destination
        finally:
            temporary.unlink(missing_ok=True)

    def write_json_once(self, name: str, value: Mapping[str, Any]) -> Path:
        if not isinstance(value, Mapping):
            raise EvidenceError("JSON evidence must be an object")
        try:
            text = json.dumps(
                value,
                ensure_ascii=False,
                sort_keys=True,
                indent=2,
                allow_nan=False,
            ) + "\n"
        except (TypeError, ValueError) as exc:
            raise EvidenceError(f"JSON evidence is invalid: {exc}") from exc
        return self.write_text_once(name, text)


@dataclass(frozen=True)
class AttemptStore:
    root: Path

    def __init__(self, root: Path | str) -> None:
        object.__setattr__(self, "root", Path(root).resolve())

    def create(self, envelope: Envelope) -> Attempt:
        attempt_root = self.root / envelope.run_id / envelope.message_id
        attempt_root.mkdir(parents=True, exist_ok=True)
        return Attempt(attempt_root)
