"""DeepSeek Harness adapter for one exact SLK Worker instance."""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import asdict
from pathlib import Path
from typing import Any, Mapping

from .base import AdapterError
from ..contracts import RESULT_SCHEMA, DeliveryResult, Endpoint, Envelope
from ..evidence import Attempt


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
    def validate_address(self, endpoint: Endpoint) -> None:
        address = endpoint.address
        if set(address) != ADDRESS_FIELDS:
            raise AdapterError("DSH_ADDRESS_INVALID", "DSH address must use the exact field set")
        _string_array(address["command"], "command")
        instance_id = address["instance_id"]
        if not isinstance(instance_id, str) or not instance_id.startswith(f"{endpoint.run_id}-"):
            raise AdapterError("DSH_ADDRESS_INVALID", "instance_id must be scoped to the endpoint Run")
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

    def _prompt(self, envelope: Envelope, result_path: Path) -> str:
        envelope_json = json.dumps(
            asdict(envelope),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        result_path_json = json.dumps(str(result_path), ensure_ascii=False)
        return (
            "SLK Worker delivery. Execute only the closed envelope below in the current CELL. "
            "When the assigned work is complete, atomically write the exact slk.worker-result/v1 object "
            "to the supplied absolute result path. A successful outer process exit without that result "
            "does not count as delivery.\n"
            f"<slk-worker-result-path>{result_path_json}</slk-worker-result-path>\n"
            f"<slk-transport-envelope>{envelope_json}</slk-transport-envelope>"
        )

    def command(self, endpoint: Endpoint, envelope: Envelope, result_path: Path) -> list[str]:
        self.validate_address(endpoint)
        address = endpoint.address
        command = _string_array(address["command"], "command")
        command.extend([str(address["instance_id"]), "--profile", "headless"])
        if address["session_id"] is not None:
            command.extend(["--resume", str(address["session_id"])])
        command.append(self._prompt(envelope, result_path))
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
        result_path = attempt.root / "worker-result.json"
        session_root = self._session_root(endpoint)
        before = self._sessions(session_root)
        environment = os.environ.copy()
        environment["DSH_RUNTIME_ROOT"] = str(endpoint.address["runtime_root"])
        command = self.command(endpoint, envelope, result_path)
        try:
            completed = subprocess.run(
                command,
                cwd=str(endpoint.address["cwd"]),
                env=environment,
                text=True,
                encoding="utf-8",
                errors="replace",
                capture_output=True,
                timeout=_positive_seconds(endpoint.address["timeout_seconds"]),
                check=False,
            )
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
        attempt.write_json_once(
            "started.json",
            {
                "message_id": envelope.message_id,
                "run_id": envelope.run_id,
                "status": "started",
                "instance_id": endpoint.address["instance_id"],
                "session_id": session_id,
            },
        )
        self._read_result(result_path, endpoint, envelope)
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
