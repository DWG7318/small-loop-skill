from __future__ import annotations

import sys
from pathlib import Path

import pytest

from slk_transport.adapters.base import AdapterError
from slk_transport.adapters.codex import CodexAdapter
from slk_transport.evidence import AttemptStore

from test_codex_adapter import codex_endpoint, supervisor_envelope


def test_initialize_conflict_keeps_diagnostic_transcript_bounded(tmp_path: Path) -> None:
    endpoint = codex_endpoint(tmp_path, "initialize-writer-flood-conflict")
    envelope = supervisor_envelope()
    attempt = AttemptStore(tmp_path / "attempts").create(envelope)

    with pytest.raises(AdapterError) as error:
        CodexAdapter().deliver(endpoint, envelope, attempt)
    assert error.value.error_code == "CODEX_ACTIVE_WRITER_UNRESOLVED"

    transcript = attempt.root / "native.stdout.txt"
    assert transcript.stat().st_size < 128 * 1024
    text = transcript.read_text(encoding="utf-8")
    assert "SLK_DIAGNOSTIC_TRUNCATED" in text
    assert "sha256=" in text
    assert "original_bytes=" in text
