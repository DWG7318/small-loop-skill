"""DeepSeek Harness adapter for one exact SLK Worker instance."""

from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any, Mapping

from .base import AdapterError
from ..contracts import RESULT_SCHEMA, DeliveryResult, Endpoint, Envelope
from ..evidence import Attempt
from ..process import windows_no_window_kwargs
from ..instance_id import validate_worker_instance_id
from ..subprocess_watch import finish, spawn
from ..task_file import create_task_file
from ..workspace import WorkspaceError, preflight_git_workspace


ADDRESS_FIELDS = frozenset(
    {
        "command",
        "instance_id",
        "session_id",
        "runtime_root",
        "cwd",
        "timeout_seconds",
    }
)
RESULT_FIELDS = frozenset(
    {
        "schema_version",
        "message_id",
        "run_id",
        "role_instance_id",
        "status",
        "candidate",
        "next_payload",
    }
)


def _positive_seconds(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        raise AdapterError("DSH_ADDRESS_INVALID", "timeout_seconds must be positive")
    return float(value)


def _string_array(value: Any, label: str) -> list[str]:
    if not isinstance(value, list) or not value or not all(isinstance(item, str) and item for item in value):
        raise AdapterError("DSH_ADDRESS_INVALID", f"{label} must be a non-empty string array")
    return list(value)


class DshAdapter:
    def __init__(self, *, monotonic=time.monotonic, sleep=time.sleep) -> None:
        self._monotonic = monotonic
        self._sleep = sleep

    def validate_address(self, endpoint: Endpoint) -> None:
        if (
            endpoint.role != "worker"
            or endpoint.agent_runtime != "dsh"
            or endpoint.adapter != "dsh-worker"
        ):
            raise AdapterError("DSH_ADDRESS_INVALID", "DSH endpoint must be the Worker adapter")
        address = endpoint.address
        if set(address) != ADDRESS_FIELDS:
            raise AdapterError("DSH_ADDRESS_INVALID", "DSH address must use the exact field set")
        _string_array(address["command"], "command")
        instance_id = address["instance_id"]
        try:
            validate_worker_instance_id(endpoint.run_id, instance_id)
        except (TypeError, ValueError) as exc:
            raise AdapterError("DSH_ADDRESS_INVALID", str(exc)) from exc
        session_id = address["session_id"]
        if session_id is not None and (
            not isinstance(session_id, str) or not session_id.startswith("session-")
        ):
            raise AdapterError("DSH_ADDRESS_INVALID", "session_id must be null or a DSH session identifier")
        for field in ("runtime_root", "cwd"):
            value = address[field]
            if not isinstance(value, str) or not Path(value).is_absolute() or not Path(value).is_dir():
                raise AdapterError("DSH_ADDRESS_INVALID", f"{field} must be an existing absolute directory")
        _positive_seconds(address["timeout_seconds"])

    @staticmethod
    def result_contract(envelope: Envelope) -> dict[str, Any]:
        return {
            "schema_version": "slk.worker-result/v1",
            "message_id": envelope.message_id,
            "run_id": envelope.run_id,
            "role_instance_id": envelope.receiver_role_instance_id,
            "status": "completed",
            "candidate": {"kind": "commit", "commit": "REPLACE_WITH_EXACT_COMMIT"},
            "next_payload": {},
        }

    @staticmethod
    def task_instruction(task_path: Path, task_sha256: str) -> str:
        return (
            "Execute only the immutable SLK task file at the absolute path below. Verify its "
            "SHA-256 before reading it; reject any mismatch or unknown field. Write only the "
            "declared result contract to its result_path.\n"
            f"<slk-transport-task path={json.dumps(str(task_path.resolve()))} "
            f"sha256={json.dumps(task_sha256)} />"
        )

    def create_task_file(
        self,
        endpoint: Endpoint,
        envelope: Envelope,
        attempt: Attempt,
        drop_root: Path,
    ) -> tuple[Path, str]:
        return create_task_file(
            attempt,
            drop_root / "transport-task.json",
            endpoint,
            envelope,
            self.result_contract(envelope),
            drop_root / "worker-result.json",
        )

    def command(self, endpoint: Endpoint, instruction: str) -> list[str]:
        self.validate_address(endpoint)
        address = endpoint.address
        command = _string_array(address["command"], "command")
        command.extend([str(address["instance_id"]), "--profile", "headless"])
        if address["session_id"] is not None:
            command.extend(["--resume", str(address["session_id"])])
        command.append(instruction)
        return command

    def _session_root(self, endpoint: Endpoint) -> Path:
        return (
            Path(str(endpoint.address["runtime_root"]))
            / "runs"
            / str(endpoint.address["instance_id"])
            / "home"
            / "storages"
            / "session_projcache"
            / "sessions"
        )

    @staticmethod
    def _sessions(root: Path) -> dict[str, Path]:
        if not root.is_dir():
            return {}
        return {path.stem: path for path in root.glob("session-*.json") if path.is_file()}

    def _resolve_session(
        self,
        endpoint: Endpoint,
        before: Mapping[str, Path],
        after: Mapping[str, Path],
    ) -> str:
        expected = endpoint.address["session_id"]
        if expected is not None:
            if expected not in after:
                raise AdapterError("DSH_SESSION_MISSING", "recorded DSH session was not present after delivery")
            return str(expected)
        created = sorted(set(after) - set(before))
        if len(created) != 1:
            raise AdapterError(
                "DSH_SESSION_AMBIGUOUS",
                f"first Worker activation created {len(created)} sessions instead of one",
            )
        return created[0]

    def _read_result(self, path: Path, endpoint: Endpoint, envelope: Envelope) -> Mapping[str, Any]:
        if not path.is_file():
            raise AdapterError("DSH_RESULT_MISSING", "DSH exited without the required Worker result")
        try:
            value = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError) as exc:
            raise AdapterError("DSH_RESULT_INVALID", "Worker result is not valid JSON") from exc
        if not isinstance(value, dict) or set(value) != RESULT_FIELDS:
            raise AdapterError("DSH_RESULT_INVALID", "Worker result does not use the closed field set")
        expected = {
            "schema_version": "slk.worker-result/v1",
            "message_id": envelope.message_id,
            "run_id": envelope.run_id,
            "role_instance_id": endpoint.role_instance_id,
            "status": "completed",
        }
        for field, expected_value in expected.items():
            if value.get(field) != expected_value:
                raise AdapterError("DSH_RESULT_INVALID", f"Worker result {field} mismatch")
        if not isinstance(value["candidate"], dict) or not isinstance(value["candidate"].get("kind"), str):
            raise AdapterError("DSH_RESULT_INVALID", "Worker result candidate is invalid")
        if not isinstance(value["next_payload"], dict):
            raise AdapterError("DSH_RESULT_INVALID", "Worker result next_payload is invalid")
        return value

    def deliver(self, endpoint: Endpoint, envelope: Envelope, attempt: Attempt) -> DeliveryResult:
        self.validate_address(endpoint)
        workspace = Path(str(endpoint.address["cwd"]))
        try:
            preflight_git_workspace(workspace)
        except WorkspaceError as exc:
            raise AdapterError("DSH_WORKSPACE_NOT_READY", str(exc)) from exc
        drop_parent = workspace / ".slk-transport"
        drop_root = drop_parent / envelope.message_id
        parent_existed = drop_parent.exists()
        try:
            drop_root.mkdir(parents=True, exist_ok=False)
        except FileExistsError as exc:
            raise AdapterError("DSH_RESULT_DROP_COLLISION", "Worker result drop already exists") from exc
        result_path = drop_root / "worker-result.json"
        session_root = self._session_root(endpoint)
        before = self._sessions(session_root)
        environment = os.environ.copy()
        environment.pop("SLK_ROLE_CREDENTIAL", None)
        environment.pop("SLK_OVERWATCHER_CREDENTIAL", None)
        environment["DSH_RUNTIME_ROOT"] = str(endpoint.address["runtime_root"])
        task_path, task_sha256 = self.create_task_file(endpoint, envelope, attempt, drop_root)
        command = self.command(endpoint, self.task_instruction(task_path, task_sha256))
        process = None
        try:
            try:
                started_at = self._monotonic()
                timeout = _positive_seconds(endpoint.address["timeout_seconds"])
                process = spawn(
                    command,
                    cwd=str(workspace),
                    env=environment,
                    process_kwargs=windows_no_window_kwargs(),
                )
                session_id: str | None = None
                while self._monotonic() - started_at < timeout:
                    after = self._sessions(session_root)
                    expected = endpoint.address["session_id"]
                    if expected is not None and expected in after and process.poll() is None:
                        session_id = str(expected)
                    elif expected is None:
                        created = sorted(set(after) - set(before))
                        if len(created) > 1:
                            process.kill()
                            process.communicate()
                            raise AdapterError(
                                "DSH_SESSION_AMBIGUOUS",
                                f"first Worker activation created {len(created)} sessions instead of one",
                            )
                        if len(created) == 1 and process.poll() is None:
                            session_id = created[0]
                    if session_id is not None:
                        attempt.write_json_once(
                            "started.json",
                            {
                                "message_id": envelope.message_id,
                                "run_id": envelope.run_id,
                                "status": "started",
                                "instance_id": endpoint.address["instance_id"],
                                "session_id": session_id,
                                "task_sha256": task_sha256,
                            },
                        )
                        break
                    if process.poll() is not None:
                        break
                    self._sleep(0.01)
                remaining = timeout - (self._monotonic() - started_at)
                completed = finish(process, remaining)
            except subprocess.TimeoutExpired as exc:
                stdout = exc.stdout if isinstance(exc.stdout, str) else ""
                stderr = exc.stderr if isinstance(exc.stderr, str) else ""
                attempt.write_text_once("native.stdout.txt", stdout)
                attempt.write_text_once("native.stderr.txt", stderr)
                raise AdapterError("DSH_TIMEOUT", "DSH Worker did not complete in time") from exc
            attempt.write_text_once("native.stdout.txt", completed.stdout)
            attempt.write_text_once("native.stderr.txt", completed.stderr)
            if completed.returncode != 0:
                raise AdapterError("DSH_EXIT_NONZERO", f"DSH Worker exited with {completed.returncode}")
            session_id = self._resolve_session(endpoint, before, self._sessions(session_root))
            if not (attempt.root / "started.json").is_file():
                raise AdapterError("DSH_START_UNPROVED", "DSH exited before native start was proven")
            try:
                worker_result = self._read_result(result_path, endpoint, envelope)
            except AdapterError:
                if result_path.is_file():
                    attempt.write_text_once(
                        "worker-result.invalid.txt",
                        result_path.read_text(encoding="utf-8-sig", errors="replace"),
                    )
                raise
            attempt.write_json_once("worker-result.json", worker_result)
            return DeliveryResult(
                schema_version=RESULT_SCHEMA,
                message_id=envelope.message_id,
                run_id=envelope.run_id,
                adapter=endpoint.adapter,
                status="completed",
                native_identity={
                    "instance_id": str(endpoint.address["instance_id"]),
                    "session_id": session_id,
                    "exit_code": completed.returncode,
                },
                error_code=None,
                evidence=(
                    "started.json",
                    "worker-result.json",
                    "native.stdout.txt",
                    "native.stderr.txt",
                ),
            )
        finally:
            result_path.unlink(missing_ok=True)
            task_path.unlink(missing_ok=True)
            try:
                drop_root.rmdir()
            except OSError:
                pass
            if not parent_existed:
                try:
                    drop_parent.rmdir()
                except OSError:
                    pass
