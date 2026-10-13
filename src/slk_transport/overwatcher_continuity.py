"""Read-only cadence inspection; method policy remains owned by transport."""
from __future__ import annotations

from typing import Any, Mapping

from slk_overwatch_tools.cadence import (
    OverwatcherContinuityError, cadence_time as _time, inspect_cadence,
)
from . import SUPPORTED_METHOD_VERSIONS


def inspect_overwatcher_cadence(projection: Mapping[str, Any], *, observed_at: str) -> dict[str, Any]:
    """Preserve the transport contract without moving version policy into helpers."""
    summary = projection.get("summary")
    version = summary.get("slk_version") if isinstance(summary, Mapping) else None
    return inspect_cadence(projection, observed_at=observed_at,
                           current_method=version in SUPPORTED_METHOD_VERSIONS,
                           native_subagent=version in {"4.5.0", "4.5.1"})
