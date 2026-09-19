from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest

from slk_transport.evidence import AttemptStore, EvidenceError

from test_contracts import Envelope, envelope_value


def test_attempt_files_are_atomic_and_message_scoped(tmp_path: Path) -> None:
    envelope = Envelope.from_dict(envelope_value())
    attempt = AttemptStore(tmp_path).create(envelope)

    attempt.write_json_once(
        "accepted.json",
        {"message_id": envelope.message_id, "status": "accepted"},
    )

    written = json.loads((attempt.root / "accepted.json").read_text(encoding="utf-8"))
    assert written == {"message_id": envelope.message_id, "status": "accepted"}
    assert attempt.root == tmp_path / "RUN-A" / envelope.message_id
    assert not list(attempt.root.glob("*.tmp"))

    with pytest.raises(EvidenceError, match="already exists"):
        attempt.write_json_once(
            "accepted.json",
            {"message_id": envelope.message_id, "status": "accepted"},
        )


def test_attempt_rejects_unsafe_evidence_names(tmp_path: Path) -> None:
    attempt = AttemptStore(tmp_path).create(Envelope.from_dict(envelope_value()))

    for name in ("../failed.json", "nested/failed.json", "", "."):
        with pytest.raises(EvidenceError, match="evidence name"):
            attempt.write_text_once(name, "unsafe")


def test_concurrent_terminal_writes_never_replace_first_evidence(tmp_path: Path) -> None:
    attempt = AttemptStore(tmp_path).create(Envelope.from_dict(envelope_value()))
    outcomes: list[str] = []

    def write(value: str) -> None:
        try:
            attempt.write_text_once("completed.json", value)
            outcomes.append("written")
        except EvidenceError:
            outcomes.append("rejected")

    first = threading.Thread(target=write, args=("first",))
    second = threading.Thread(target=write, args=("second",))
    first.start()
    second.start()
    first.join()
    second.join()

    assert sorted(outcomes) == ["rejected", "written"]
    assert (attempt.root / "completed.json").read_text(encoding="utf-8") in {"first", "second"}
    assert not list(attempt.root.glob("*.tmp"))
