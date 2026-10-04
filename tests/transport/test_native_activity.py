from __future__ import annotations

import errno
import json
from pathlib import Path

import pytest

from slk_transport.native_activity import (
    NativeActivityError,
    inspect_native_activity,
    validate_native_task_activity,
    validate_native_start,
)


def test_core_atomic_projection_retries_windows_busy_without_losing_last_good(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    import slk_transport.native_activity as activity

    target = tmp_path / "projection.json"
    activity._atomic_json(target, {"sequence": 1})
    real_replace = activity.os.replace
    attempts = 0

    def replace(source, destination):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise OSError(errno.EPERM, "busy once")
        real_replace(source, destination)

    monkeypatch.setattr(activity.os, "replace", replace)
    monkeypatch.setattr(activity.time, "sleep", lambda _seconds: None)

    activity._atomic_json(target, {"sequence": 2})

    assert attempts == 2
    assert json.loads(target.read_text(encoding="utf-8")) == {"sequence": 2}
    assert list(tmp_path.glob(".projection.json.*.tmp")) == []


def test_native_activity_tail_is_metadata_only_and_bounded_to_twelve() -> None:
    base = {
        "schema_version": "slk.native-task-activity/v1",
        "adapter": "dsh-worker",
        "run_id": "RUN-A",
        "cell_id": "CELL-001",
        "message_id": "11111111-1111-4111-8111-111111111111",
        "native_task_id": "session-a",
        "status": "RUNNING",
        "sequence": 13,
        "observed_at": "2026-10-01T00:05:00Z",
        "last_event": {
            "kind": "DSH_SESSION_EVENT",
            "sequence": 13,
            "detail_sha256": "a" * 64,
            "tail": [
                {
                    "kind": "DSH_SESSION_EVENT",
                    "sequence": index,
                    "observed_at": "2026-10-01T00:05:00Z",
                    "detail_sha256": "b" * 64,
                }
                for index in range(1, 14)
            ],
        },
        "waiting_on": "DSH_AGENT",
    }

    with pytest.raises(NativeActivityError, match="at most twelve"):
        validate_native_task_activity(
            base,
            adapter="dsh-worker",
            run_id="RUN-A",
            cell_id="CELL-001",
            message_id="11111111-1111-4111-8111-111111111111",
            observed_at="2026-10-01T00:05:00Z",
        )

    base["last_event"]["tail"] = [
        {
            "kind": "DSH_SESSION_EVENT",
            "sequence": 13,
            "observed_at": "2026-10-01T00:05:00Z",
            "detail_sha256": "b" * 64,
            "text": "model output must never enter the native tail",
        }
    ]
    with pytest.raises(NativeActivityError, match="metadata-only"):
        validate_native_task_activity(
            base,
            adapter="dsh-worker",
            run_id="RUN-A",
            cell_id="CELL-001",
            message_id="11111111-1111-4111-8111-111111111111",
            observed_at="2026-10-01T00:05:00Z",
        )


def test_windows_retained_handle_of_exited_process_is_not_alive(monkeypatch):
    import os
    import types
    import slk_transport.native_activity as activity
    if os.name != 'nt': pytest.skip('Windows kernel identity contract')
    closed = []
    def times(handle, created, exited, kernel, user):
        created._obj.value = 123
        exited._obj.value = 456
        return True
    kernel = types.SimpleNamespace(OpenProcess=lambda *a:7, GetProcessTimes=times,
                                   CloseHandle=lambda handle:closed.append(handle))
    monkeypatch.setattr(activity.ctypes, 'WinDLL', lambda *a,**k:kernel)
    assert activity.process_probe(7, 'win-filetime:123') == {'exists':False,'identity_matches':False}
    assert closed == [7]


def _start_receipt(tmp_path: Path, *, native_task_kind: str = "ocrv-session") -> Path:
    path = tmp_path / "started.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": "slk.native-start/v2",
                "status": "STARTED",
                "adapter": "ocrv-checker",
                "run_id": "RUN-A",
                "cell_id": "CELL-001",
                "message_id": "11111111-1111-4111-8111-111111111111",
                "request_sha256": "a" * 64,
                "native_request_sha256": "b" * 64,
                "observed_at": "2026-10-01T00:00:00Z",
                "process": {"pid": 4321, "creation_time": "2026-10-01T00:00:00.0000000Z"},
                "native_task": {
                    "kind": native_task_kind,
                    "id": "ocrv-session-a",
                    "status": "RUNNING",
                },
            }
        ),
        encoding="utf-8",
    )
    return path


def _terminal(path: Path, *, message_id: str, status: str) -> Path:
    path.write_text(
        json.dumps(
            {
                "schema_version": "slk.transport-result/v1",
                "message_id": message_id,
                "run_id": "RUN-A",
                "adapter": "ocrv-checker",
                "status": status,
                "native_identity": {},
                "error_code": None if status == "completed" else "OCRV_FAILED",
                "evidence": ["started.json"],
            }
        ),
        encoding="utf-8",
    )
    return path


def test_legacy_started_file_is_not_native_start_evidence(tmp_path: Path) -> None:
    legacy = tmp_path / "started.json"
    legacy.write_text(
        json.dumps(
            {
                "message_id": "11111111-1111-4111-8111-111111111111",
                "run_id": "RUN-A",
                "status": "started",
                "transport_invocation_id": "old-wrapper-only",
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(NativeActivityError, match="slk.native-start/v2"):
        validate_native_start(
            legacy,
            adapter="ocrv-checker",
            run_id="RUN-A",
            cell_id="CELL-001",
            message_id="11111111-1111-4111-8111-111111111111",
            request_sha256="a" * 64,
        )


def test_native_start_binds_exact_request_process_and_native_task(tmp_path: Path) -> None:
    receipt = _start_receipt(tmp_path)

    value = validate_native_start(
        receipt,
        adapter="ocrv-checker",
        run_id="RUN-A",
        cell_id="CELL-001",
        message_id="11111111-1111-4111-8111-111111111111",
        request_sha256="a" * 64,
    )

    assert value["process"]["pid"] == 4321
    assert value["native_task"] == {
        "kind": "ocrv-session",
        "id": "ocrv-session-a",
        "status": "RUNNING",
    }


def test_read_only_activity_reports_dead_identity_without_mutating_or_waking(tmp_path: Path) -> None:
    receipt = _start_receipt(tmp_path)
    before = receipt.read_bytes()

    result = inspect_native_activity(
        receipt,
        process_probe=lambda _pid, _created: {"exists": False, "identity_matches": False},
        native_probe=lambda _start: pytest.fail("dead process must not query or wake a native task"),
        observed_at="2026-10-01T00:05:00Z",
    )

    assert result["status"] == "DEAD_WITHOUT_TERMINAL"
    assert result["process"] == {"exists": False, "identity_matches": False}
    assert receipt.read_bytes() == before


def test_wrong_message_terminal_cannot_complete_the_started_delivery(tmp_path: Path) -> None:
    receipt = _start_receipt(tmp_path)
    completed = _terminal(
        tmp_path / "completed.json",
        message_id="22222222-2222-4222-8222-222222222222",
        status="completed",
    )

    result = inspect_native_activity(
        receipt,
        terminal_paths=(completed,),
        process_probe=lambda _pid, _created: pytest.fail(
            "mismatched terminal evidence must fail closed before a process inference"
        ),
        observed_at="2026-10-01T00:05:00Z",
    )

    assert result["status"] == "UNKNOWN"
    assert result["terminal_evidence"] is None
    assert result["error"] == "TERMINAL_EVIDENCE_IDENTITY_MISMATCH"


def test_exact_unique_terminal_completes_without_a_liveness_probe(tmp_path: Path) -> None:
    receipt = _start_receipt(tmp_path)
    completed = _terminal(
        tmp_path / "completed.json",
        message_id="11111111-1111-4111-8111-111111111111",
        status="completed",
    )

    result = inspect_native_activity(
        receipt,
        terminal_paths=(completed,),
        process_probe=lambda _pid, _created: pytest.fail(
            "an exact terminal result supersedes a liveness probe"
        ),
        observed_at="2026-10-01T00:05:00Z",
    )

    assert result["status"] == "COMPLETED"
    assert result["terminal_evidence"] == str(completed)
    assert result["error"] is None


def test_conflicting_terminal_files_cannot_choose_a_convenient_outcome(tmp_path: Path) -> None:
    receipt = _start_receipt(tmp_path)
    message_id = "11111111-1111-4111-8111-111111111111"
    completed = _terminal(tmp_path / "completed.json", message_id=message_id, status="completed")
    failed = _terminal(tmp_path / "failed.json", message_id=message_id, status="failed")

    result = inspect_native_activity(
        receipt,
        terminal_paths=(completed, failed),
        process_probe=lambda _pid, _created: pytest.fail(
            "conflicting terminal evidence must fail closed before a process inference"
        ),
        observed_at="2026-10-01T00:05:00Z",
    )

    assert result["status"] == "UNKNOWN"
    assert result["terminal_evidence"] is None
    assert result["error"] == "TERMINAL_EVIDENCE_CONFLICT"


def test_read_only_activity_keeps_probe_failure_unknown(tmp_path: Path) -> None:
    receipt = _start_receipt(tmp_path)

    result = inspect_native_activity(
        receipt,
        process_probe=lambda _pid, _created: {"exists": True, "identity_matches": True},
        native_probe=lambda _start: (_ for _ in ()).throw(OSError("native query unavailable")),
        observed_at="2026-10-01T00:05:00Z",
    )

    assert result["status"] == "UNKNOWN"
    assert result["error"] == "NATIVE_QUERY_FAILED"


def test_process_probe_access_failure_is_unknown_not_dead(tmp_path: Path) -> None:
    receipt = _start_receipt(tmp_path)

    result = inspect_native_activity(
        receipt,
        process_probe=lambda _pid, _created: (_ for _ in ()).throw(
            PermissionError("access denied")
        ),
        native_probe=lambda _start: pytest.fail(
            "an unavailable process identity must not be treated as a live task"
        ),
        observed_at="2026-10-01T00:05:00Z",
    )

    assert result["status"] == "UNKNOWN"
    assert result["process"] == {"exists": None, "identity_matches": None}
    assert result["error"] == "PROCESS_PROBE_FAILED"


def test_desktop_turn_uses_platform_activity_not_short_lived_cli_pid(tmp_path: Path) -> None:
    receipt = _start_receipt(tmp_path, native_task_kind="codex-desktop-turn")

    result = inspect_native_activity(
        receipt,
        process_probe=lambda _pid, _created: pytest.fail(
            "the completed Desktop bridge CLI is not the turn executor"
        ),
        native_probe=lambda _start: {
            "schema_version": "slk.native-task-activity/v1",
            "adapter": "ocrv-checker",
            "run_id": "RUN-A",
            "cell_id": "CELL-001",
            "message_id": "11111111-1111-4111-8111-111111111111",
            "native_task_id": "ocrv-session-a",
            "status": "RUNNING",
            "sequence": 8,
            "observed_at": "2026-10-01T00:04:59Z",
            "last_event": {"kind": "PLATFORM_TURN_ACTIVE", "sequence": 8},
            "waiting_on": "CODEX_TURN",
        },
        observed_at="2026-10-01T00:05:00Z",
    )

    assert result["status"] == "ACTIVE"
    assert result["process"] is None
    assert result["error"] is None


def test_live_wrapper_without_current_native_projection_is_unknown(tmp_path: Path) -> None:
    receipt = _start_receipt(tmp_path)

    result = inspect_native_activity(
        receipt,
        process_probe=lambda _pid, _created: {"exists": True, "identity_matches": True},
        observed_at="2026-10-01T00:05:00Z",
        max_activity_age_seconds=240,
    )

    assert result["status"] == "UNKNOWN"
    assert result["error"] == "NATIVE_ACTIVITY_MISSING"


def test_stale_or_wrong_session_activity_never_inherits_started_running(tmp_path: Path) -> None:
    receipt = _start_receipt(tmp_path)
    activity = tmp_path / "native-activity.json"
    activity.write_text(
        json.dumps(
            {
                "schema_version": "slk.native-task-activity/v1",
                "adapter": "ocrv-checker",
                "run_id": "RUN-A",
                "cell_id": "CELL-001",
                "message_id": "11111111-1111-4111-8111-111111111111",
                "native_task_id": "some-other-session",
                "status": "RUNNING",
                "sequence": 7,
                "observed_at": "2026-10-01T00:00:00Z",
                "last_event": {"kind": "OCRV_PROGRESS", "sequence": 7},
                "waiting_on": "OCRV_REVIEW",
            }
        ),
        encoding="utf-8",
    )

    result = inspect_native_activity(
        receipt,
        process_probe=lambda _pid, _created: {"exists": True, "identity_matches": True},
        observed_at="2026-10-01T00:05:00Z",
        max_activity_age_seconds=240,
    )

    assert result["status"] == "UNKNOWN"
    assert result["error"] in {"NATIVE_ACTIVITY_IDENTITY_MISMATCH", "NATIVE_ACTIVITY_STALE"}


def test_later_ocrv_segment_activity_supersedes_exited_first_segment(tmp_path: Path) -> None:
    receipt = _start_receipt(tmp_path, native_task_kind="ocrv-review")
    segment_root = tmp_path / "review-segments" / "segment-002"
    segment_root.mkdir(parents=True)
    segment_start = segment_root / "started.json"
    segment_start.write_text(
        json.dumps(
            {
                "schema_version": "slk.native-start/v2",
                "status": "STARTED",
                "adapter": "ocrv-checker",
                "run_id": "RUN-A",
                "cell_id": "CELL-001",
                "message_id": "11111111-1111-4111-8111-111111111111",
                "request_sha256": "a" * 64,
                "native_request_sha256": "c" * 64,
                "observed_at": "2026-10-01T00:04:58Z",
                "process": {"pid": 9876, "creation_time": "segment-two-created"},
                "native_task": {
                    "kind": "ocrv-review",
                    "id": "ocrv-session-segment-two",
                    "status": "RUNNING",
                },
            }
        ),
        encoding="utf-8",
    )
    (segment_root / "native-activity.json").write_text(
        json.dumps(
            {
                "schema_version": "slk.native-task-activity/v1",
                "adapter": "ocrv-checker",
                "run_id": "RUN-A",
                "cell_id": "CELL-001",
                "message_id": "11111111-1111-4111-8111-111111111111",
                "native_task_id": "ocrv-session-segment-two",
                "status": "RUNNING",
                "sequence": 3,
                "observed_at": "2026-10-01T00:04:59Z",
                "last_event": {"kind": "OCRV_PROGRESS", "sequence": 3},
                "waiting_on": "OCRV_REVIEW",
            }
        ),
        encoding="utf-8",
    )
    probed: list[int] = []

    def probe(pid: int, _created: str) -> dict[str, bool]:
        probed.append(pid)
        return {"exists": pid == 9876, "identity_matches": pid == 9876}

    result = inspect_native_activity(
        receipt,
        process_probe=probe,
        observed_at="2026-10-01T00:05:00Z",
    )

    assert result["status"] == "ACTIVE"
    assert result["native_task"]["id"] == "ocrv-session-segment-two"
    assert probed == [9876]
