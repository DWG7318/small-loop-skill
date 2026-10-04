"""A2: host-only preparation must exercise the actual credential consumer."""

import os

import pytest

from slk_transport import worker_completion as completion


SYNTHETIC = "slk_" + "a" * 64


@pytest.mark.skipif(os.name != "nt", reason="CurrentUser DPAPI is Windows-only")
def test_plaintext_is_not_silently_accepted_as_sealed_checker_credential(tmp_path):
    source = tmp_path / "checker.credential"
    source.write_text(SYNTHETIC, encoding="ascii")
    with pytest.raises(completion.CompletionError) as failure:
        completion._default_checker_authenticate("RUN-TEST", "checker-test", source, [])
    assert failure.value.error_code == "CHECKER_CREDENTIAL_UNAVAILABLE"
    assert "sealed" in str(failure.value).lower()
    assert SYNTHETIC not in str(failure.value)


@pytest.mark.skipif(os.name != "nt", reason="CurrentUser DPAPI is Windows-only")
def test_prepare_seals_and_roundtrips_using_real_consumer_without_exposing_secret(tmp_path, monkeypatch):
    source = tmp_path / "source.credential"
    target = tmp_path / "checker.dpapi"
    source.write_text(SYNTHETIC, encoding="ascii")
    seen = []

    def authenticate(command, arguments, *, credential):
        assert credential == SYNTHETIC
        seen.append(arguments)
        return {"status": "authenticated", "run_id": "RUN-TEST", "role": "checker",
                "role_instance_id": "checker-test", "runtime_revision": 7}

    monkeypatch.setattr(completion, "_run_json_command", authenticate)
    receipt = completion.prepare_sealed_role_credential(
        source, target, run_id="RUN-TEST", role="checker", role_instance_id="checker-test",
        state_command=["state"],
    )
    assert len(seen) == 2  # before sealing and through the saved consumer
    assert completion.unprotect_dpapi_hex(target) == SYNTHETIC
    assert SYNTHETIC not in str(receipt)
    assert SYNTHETIC.encode() not in target.read_bytes()
    assert receipt["status"] == "SEALED_ROLE_VERIFIED"
    assert source.read_text() == SYNTHETIC  # never delete or rewrite original input
    original = target.read_bytes()
    with pytest.raises(completion.CompletionError):
        completion.prepare_sealed_role_credential(
            source, target, run_id="RUN-TEST", role="checker", role_instance_id="checker-test",
            state_command=["state"],
        )
    assert target.read_bytes() == original


@pytest.mark.skipif(os.name != "nt", reason="CurrentUser DPAPI is Windows-only")
def test_wrong_role_cannot_be_sealed_for_checker(tmp_path, monkeypatch):
    source = tmp_path / "source.credential"
    target = tmp_path / "checker.dpapi"
    source.write_text(SYNTHETIC, encoding="ascii")
    monkeypatch.setattr(completion, "_run_json_command", lambda *a, **kw: {
        "role": "worker", "role_instance_id": "checker-test", "runtime_revision": 7,
    })
    with pytest.raises(completion.CompletionError):
        completion.prepare_sealed_role_credential(
            source, target, run_id="RUN-TEST", role="checker", role_instance_id="checker-test",
            state_command=["state"],
        )
    assert not target.exists()


@pytest.mark.skipif(os.name != "nt", reason="CurrentUser DPAPI is Windows-only")
@pytest.mark.parametrize("field,value", [("status", "rejected"), ("run_id", "another-run"),
                                         ("runtime_revision", True), ("runtime_revision", 0)])
def test_consumer_identity_requires_authenticated_run_and_valid_revision(tmp_path, monkeypatch, field, value):
    source, target = tmp_path / "source.credential", tmp_path / "sealed.dpapi"
    source.write_text(SYNTHETIC, encoding="ascii")
    result = {"status": "authenticated", "run_id": "RUN-TEST", "role": "checker",
              "role_instance_id": "checker-test", "runtime_revision": 7, field: value}
    monkeypatch.setattr(completion, "_run_json_command", lambda *a, **kw: result)
    with pytest.raises(completion.CompletionError):
        completion.prepare_sealed_role_credential(
            source, target, run_id="RUN-TEST", role="checker", role_instance_id="checker-test",
            state_command=["state"],
        )
    assert not target.exists()


@pytest.mark.skipif(os.name != "nt", reason="CurrentUser DPAPI is Windows-only")
def test_real_state_authentication_and_saved_consumer(tmp_path, monkeypatch):
    from test_worker_completion import actual_worker_state

    state, config, worker_secret, _checker_secret, revision = actual_worker_state(tmp_path)
    monkeypatch.setenv("SLK_CONFIG_PATH", str(config))
    source, target = tmp_path / "worker.credential", tmp_path / "worker.dpapi"
    source.write_text(worker_secret, encoding="ascii")
    receipt = completion.prepare_sealed_role_credential(
        source, target, run_id="RUN-A", role="worker", role_instance_id="RUN-A-worker-001",
        state_command=[str(state)],
    )
    assert receipt["runtime_revision"] == revision
    assert completion.unprotect_dpapi_hex(target) == worker_secret
    assert worker_secret not in str(receipt)
