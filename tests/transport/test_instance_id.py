from __future__ import annotations

import pytest

from slk_transport.instance_id import expected_worker_instance_id, validate_worker_instance_id


def test_short_and_long_worker_instance_ids_are_exact_and_bounded() -> None:
    assert expected_worker_instance_id("RUN-A") == "RUN-A-worker"
    long_run = "RUN-" + "X" * 180
    first = expected_worker_instance_id(long_run)
    second = expected_worker_instance_id(long_run)
    assert first == second
    assert len(first) <= 64
    assert first.endswith("-worker-" + first.rsplit("-", 1)[-1])
    validate_worker_instance_id(long_run, first)


def test_worker_instance_cannot_use_an_arbitrary_prefix_or_overlong_identity() -> None:
    run_id = "RUN-" + "X" * 180
    with pytest.raises(ValueError):
        validate_worker_instance_id(run_id, run_id[:50] + "-worker")
    with pytest.raises(ValueError):
        validate_worker_instance_id("RUN-A", "RUN-A-worker-extra")
