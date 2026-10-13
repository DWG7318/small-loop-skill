"""Registered native identity is not a name derived from the business Run."""
from dataclasses import replace
from pathlib import Path

import pytest

from slk_transport.adapters.base import AdapterError
from slk_transport.adapters.dsh import DshAdapter
from slk_transport.evidence import AttemptStore
from test_dsh_adapter import worker_endpoint, worker_envelope


def test_registered_native_instance_keeps_its_exact_home_and_resume_command(tmp_path):
    endpoint = worker_endpoint(tmp_path, run_id="SLK-RUN-LCAS-RC08-HOOK-ASK-PROJECTION-R2",
                               session_id="session-34008a12-dfaa-4375-87e0-ea42c56cd34b")
    endpoint = replace(endpoint, address={**endpoint.address, "instance_id": "lcas-r07-r2-worker"})
    adapter = DshAdapter()
    adapter.validate_address(endpoint)
    command = adapter.command(endpoint, "task")
    assert command[-6:] == ["lcas-r07-r2-worker", "--profile", "headless", "--resume",
                            endpoint.address["session_id"], "task"]
    assert adapter._session_root(endpoint) == (Path(endpoint.address["runtime_root"]) / "runs"
        / "lcas-r07-r2-worker/home/storages/session_projcache/sessions")


def test_registered_native_instance_resumes_original_session_without_creating_another(tmp_path):
    session_id = "session-34008a12-dfaa-4375-87e0-ea42c56cd34b"
    endpoint = worker_endpoint(tmp_path, session_id=session_id)
    endpoint = replace(endpoint, address={**endpoint.address, "instance_id": "lcas-r07-r2-worker"})
    adapter = DshAdapter()
    root = adapter._session_root(endpoint)
    root.mkdir(parents=True)
    original = root / f"{session_id}.json"
    original.write_bytes(b"{}\n")
    envelope = worker_envelope()
    attempt = AttemptStore(tmp_path / "attempts").create(envelope)
    result = adapter.deliver(endpoint, envelope, attempt)
    assert result.status == "completed"
    assert result.native_identity["instance_id"] == "lcas-r07-r2-worker"
    assert result.native_identity["session_id"] == session_id
    assert original.read_bytes() == b"{}\n"
    assert list(root.glob("session-*.json")) == [original]
    assert not (Path(endpoint.address["runtime_root"]) / "runs/RUN-A-worker").exists()


@pytest.mark.parametrize("instance_id", [None, 1, "", "../worker", "..\\worker", "/absolute",
    "C:\\worker", "a/b", " worker", "worker ", "-worker", ".", "..", "x" * 65, "a\nb"])
def test_registered_native_instance_still_rejects_unsafe_path_or_launcher_names(tmp_path, instance_id):
    endpoint = worker_endpoint(tmp_path)
    endpoint = replace(endpoint, address={**endpoint.address, "instance_id": instance_id})
    with pytest.raises(AdapterError) as failure:
        DshAdapter().validate_address(endpoint)
    assert failure.value.error_code == "DSH_ADDRESS_INVALID"
