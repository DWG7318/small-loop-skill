"""Small bounded JSON-RPC stdio client for Codex App Server."""

from __future__ import annotations

import json
import queue
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from .adapters.base import AdapterError


class JsonRpcProcess:
    def __init__(self, command: Sequence[str], cwd: Path) -> None:
        self._process = subprocess.Popen(
            list(command),
            cwd=cwd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
        if self._process.stdin is None or self._process.stdout is None or self._process.stderr is None:
            self._process.kill()
            raise AdapterError("CODEX_PROCESS_PIPE_FAILED", "Codex App Server pipes are unavailable")
        self._queue: queue.Queue[str | None] = queue.Queue()
        self.messages: list[dict[str, Any]] = []
        self.transcript: list[str] = []
        self.stderr_lines: list[str] = []
        self._stdout_thread = threading.Thread(target=self._read_stdout, daemon=True)
        self._stderr_thread = threading.Thread(target=self._read_stderr, daemon=True)
        self._stdout_thread.start()
        self._stderr_thread.start()

    def _read_stdout(self) -> None:
        assert self._process.stdout is not None
        for line in self._process.stdout:
            self._queue.put(line)
        self._queue.put(None)

    def _read_stderr(self) -> None:
        assert self._process.stderr is not None
        for line in self._process.stderr:
            self.stderr_lines.append(line.rstrip("\r\n"))

    def send(self, value: Mapping[str, Any]) -> None:
        assert self._process.stdin is not None
        encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        self.transcript.append(f"C {encoded}")
        try:
            self._process.stdin.write(encoded + "\n")
            self._process.stdin.flush()
        except (BrokenPipeError, OSError) as exc:
            raise AdapterError("CODEX_PROCESS_CLOSED", "Codex App Server closed its input") from exc

    def _receive(self, timeout: float) -> dict[str, Any]:
        try:
            line = self._queue.get(timeout=timeout)
        except queue.Empty as exc:
            raise TimeoutError from exc
        if line is None:
            raise AdapterError(
                "CODEX_PROCESS_EXITED",
                f"Codex App Server exited with code {self._process.poll()}",
            )
        text = line.rstrip("\r\n")
        self.transcript.append(f"S {text}")
        try:
            value = json.loads(text)
        except json.JSONDecodeError as exc:
            raise AdapterError("CODEX_PROTOCOL_INVALID", "Codex App Server emitted non-JSON stdout") from exc
        if not isinstance(value, dict):
            raise AdapterError("CODEX_PROTOCOL_INVALID", "Codex App Server message is not an object")
        self.messages.append(value)
        return value

    def request(
        self,
        request_id: int,
        method: str,
        params: Mapping[str, Any],
        timeout: float,
    ) -> Mapping[str, Any]:
        self.send({"id": request_id, "method": method, "params": dict(params)})
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError
            message = self._receive(remaining)
            if message.get("id") != request_id:
                continue
            if "error" in message:
                raise AdapterError("CODEX_RPC_ERROR", json.dumps(message["error"], ensure_ascii=False))
            result = message.get("result")
            if not isinstance(result, Mapping):
                raise AdapterError("CODEX_PROTOCOL_INVALID", f"{method} result is not an object")
            return result

    def notify(self, method: str, params: Mapping[str, Any] | None = None) -> None:
        message: dict[str, Any] = {"method": method}
        if params is not None:
            message["params"] = dict(params)
        self.send(message)

    def wait_for(
        self,
        method: str,
        predicate: Callable[[Mapping[str, Any]], bool],
        timeout: float,
        *,
        after: int = 0,
    ) -> Mapping[str, Any]:
        deadline = time.monotonic() + timeout
        cursor = after
        while True:
            while cursor < len(self.messages):
                message = self.messages[cursor]
                cursor += 1
                params = message.get("params")
                if message.get("method") == method and isinstance(params, Mapping) and predicate(params):
                    return params
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError
            self._receive(remaining)

    def close(self) -> None:
        if self._process.stdin is not None:
            try:
                self._process.stdin.close()
            except OSError:
                pass
        if self._process.poll() is None:
            self._process.terminate()
            try:
                self._process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self._process.kill()
                self._process.wait(timeout=2)
        self._stdout_thread.join(timeout=1)
        self._stderr_thread.join(timeout=1)
