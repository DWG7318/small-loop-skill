"""Shared adapter interface and errors."""

from __future__ import annotations

from typing import Protocol

from ..contracts import DeliveryResult, Endpoint, Envelope
from ..evidence import Attempt


class AdapterError(RuntimeError):
    """A native runtime rejected or could not prove delivery."""

    def __init__(self, error_code: str, message: str) -> None:
        super().__init__(message)
        self.error_code = error_code


class Adapter(Protocol):
    def validate_address(self, endpoint: Endpoint) -> None: ...

    def deliver(
        self,
        endpoint: Endpoint,
        envelope: Envelope,
        attempt: Attempt,
    ) -> DeliveryResult: ...
