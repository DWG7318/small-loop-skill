"""A3: recover evidence from an immutable INCOMPLETE, never manufacture completion."""

import hashlib
import json
import subprocess
from pathlib import Path

import pytest

from slk_transport import worker_completion as wc
from slk_transport import cli
from slk_transport.contracts import canonical_json_sha256
from test_worker_completion import completion_fixture, runtime_projection, write_json


def prepared_incomplete(tmp_path):
    attempt, worker, checker = completion_fixture(tmp_path)
    repo = Path(worker["address"]["cwd"])

    def git(*args):
        return subprocess.check_output(["git", "-C", str(repo), *args], text=True).strip()

    git("init", "-q")
    (repo / "example.py").write_text("value = 0\n")
    git("add", ".")
    git("-c", "user.name=SLK test", "-c", "user.email=slk@example.invalid", "commit", "-qm", "baseline")
    baseline = git("rev-parse", "HEAD")
    (repo / "example.py").write_text("value = 1\n")
    git("add", ".")
    git("-c", "user.name=SLK test", "-c", "user.email=slk@example.invalid", "commit", "-qm", "candidate")
    candidate = {"kind": "commit", "commit": git("rev-parse", "HEAD")}
    source = json.loads((attempt / "envelope.json").read_text())
    source["token_sequence"] = 14
    write_json(attempt / "envelope.json", source)
    proof = tmp_path / "d0-test.txt"
    proof.write_text("one focused test passed\n")
    payload = {"repository": str(repo), "candidate": candidate, "cell_goal": source["payload"]["cell_goal"],
               "d1_criteria": source["payload"]["d1_criteria"], "evidence_files": [str(proof)]}
    staged = {**source, "message_id": wc._stable_id(source["message_id"], "candidate-ready"),
              "token_sequence": 15, "sender_role": "worker", "sender_role_instance_id": worker["role_instance_id"],
              "receiver_role": "checker", "receiver_role_instance_id": checker["role_instance_id"],
              "receiver_endpoint_version": checker["endpoint_version"], "payload_type": "CANDIDATE_READY",
              "payload": payload, "payload_sha256": canonical_json_sha256(payload)}
    staged_path = write_json(tmp_path / "candidate-envelope.json", staged)
    d0 = {"run_id": source["run_id"], "go_id": source["go_id"], "cell_id": source["cell_id"],
          "attempt": 1, "plan_revision": 1, "role_instance_id": worker["role_instance_id"],
          "event_id": "prepared-d0", "event_type": "D0_COMPLETED", "corrects_event_id": None,
          "occurred_at": "2026-10-04T00:00:00Z", "details": {
              "candidate": candidate, "baseline_commit": baseline, "branch": git("branch", "--show-current"),
              "changed_paths": ["example.py"], "d0": "focused test passed", "unproved": []}}
    d0_path = write_json(tmp_path / "d0.json", d0)
    terminal = json.loads((attempt / "completed.json").read_text())
    (attempt / "completed.json").unlink()
    terminal.update(status="failed", error_code="DSH_WORKER_INCOMPLETE")
    terminal["native_identity"].update(worker_outcome="incomplete", blocker_cause="ENVIRONMENT_SANDBOX_WRITE_DENIED")
    write_json(attempt / "failed.json", terminal)
    original = {"schema_version": "slk.worker-result/v1", "message_id": source["message_id"],
                "run_id": source["run_id"], "role_instance_id": worker["role_instance_id"],
                "status": "incomplete", "candidate": None, "next_payload": None,
                "blocker": {"phase": "worker-suffix-handoff", "cause": "ENVIRONMENT_SANDBOX_WRITE_DENIED",
                            "summary": "candidate exists but host writes were denied",
                            "evidence": [f"{p} sha256={hashlib.sha256(p.read_bytes()).hexdigest()} (preserved)"
                                         for p in (staged_path, d0_path, proof)]}}
    write_json(attempt / "worker-result.json", original)
    return attempt, staged_path, d0_path, checker


def test_valid_incomplete_is_eligible_without_changing_original(tmp_path):
    attempt, staged, d0, checker = prepared_incomplete(tmp_path)
    original = (attempt / "worker-result.json").read_bytes()
    receipt = wc.prepare_incomplete_worker_handoff(attempt, staged_envelope_path=staged, d0_request_path=d0)
    assert receipt["schema_version"] == "slk.worker-handoff-evidence/v1"
    assert receipt["status"] == "HANDOFF_EVIDENCE_VERIFIED"
    assert (attempt / "worker-result.json").read_bytes() == original
    assert not (attempt / "completed.json").exists()
    request = wc.build_continuation_request(
        attempt, checker, runtime_projection(), plan_revision=1, runtime_revision=7, token_sequence=14,
        credential_path=tmp_path / "worker.dpapi", state_command=["state"], transport_command=["transport"],
        occurred_at="2026-10-04T00:00:00Z",
    )
    assert request["recovery_mode"] == "INCOMPLETE_HANDOFF"
    writes = []

    def stage(endpoint, envelope):
        endpoint_path = write_json(tmp_path / "out-endpoint.json", endpoint)
        envelope_path = write_json(tmp_path / "out-envelope.json", envelope)
        return {"status": "delivery_ready", "endpoint_path": str(endpoint_path),
                "envelope_path": str(envelope_path), "attempt_root": str(tmp_path / "next-attempts")}

    result = wc.run_worker_continuation(request, authenticate=lambda *a: 7 + len(writes),
                                      write_event=lambda event: writes.append(event), start_checker=stage,
                                      commit_start=lambda _: pytest.fail("must stage only"), defer_checker_start=True)
    assert result["status"] == "CHECKER_DELIVERY_READY"
    assert json.loads(Path(result["envelope_path"]).read_text()) == json.loads(staged.read_text())
    assert [event["event_type"] for event in writes] == ["WORK_STARTED", "D0_COMPLETED", "CANDIDATE_SUBMITTED"]
    assert (attempt / "worker-result.json").read_bytes() == original


def test_incomplete_preparation_is_available_through_standard_cli(tmp_path, capsys):
    attempt, staged, d0, _checker = prepared_incomplete(tmp_path)
    assert cli.main(["prepare-incomplete-handoff", "--source-attempt", str(attempt),
                     "--staged-envelope", str(staged), "--d0-request", str(d0)]) == 0
    receipt = json.loads(capsys.readouterr().out)
    assert receipt["status"] == "HANDOFF_EVIDENCE_VERIFIED"


@pytest.mark.parametrize("mutation", ["d0_changed", "wrong_candidate", "wrong_scope", "dirty_repo", "unhashed_evidence", "new_message"])
def test_incomplete_recovery_rejects_unproved_or_changed_facts(tmp_path, mutation):
    attempt, staged, d0, _checker = prepared_incomplete(tmp_path)
    if mutation == "dirty_repo":
        (tmp_path / "repository" / "example.py").write_text("changed again\n")
    elif mutation == "d0_changed":
        d0.write_text(d0.read_text() + " ")
    else:
        payload = json.loads(staged.read_text())
        if mutation == "wrong_candidate":
            payload["payload"]["candidate"]["commit"] = "a" * 40
        elif mutation == "wrong_scope":
            payload["cell_id"] = "CELL-OTHER"
        elif mutation == "new_message":
            payload["message_id"] = "ffffffff-ffff-4fff-8fff-ffffffffffff"
        else:
            proof = tmp_path / "unbound.txt"
            proof.write_text("unbound")
            payload["payload"]["evidence_files"].append(str(proof))
        payload["payload_sha256"] = canonical_json_sha256(payload["payload"])
        write_json(staged, payload)
        # Even freshly hashed clues cannot authorize a wrong scope or candidate.
        original = json.loads((attempt / "worker-result.json").read_text())
        original["blocker"]["evidence"][0] = f"{staged} sha256={hashlib.sha256(staged.read_bytes()).hexdigest()}"
        write_json(attempt / "worker-result.json", original)
    with pytest.raises(wc.CompletionError):
        wc.prepare_incomplete_worker_handoff(attempt, staged_envelope_path=staged, d0_request_path=d0)
    assert not (attempt / "incomplete-handoff" / "evidence.json").exists()


def test_owning_host_uses_native_identity_not_model_environment(tmp_path, monkeypatch):
    attempt, staged, d0, checker = prepared_incomplete(tmp_path)
    wc.prepare_incomplete_worker_handoff(attempt, staged_envelope_path=staged, d0_request_path=d0)
    request = wc.build_continuation_request(
        attempt, checker, runtime_projection(), plan_revision=1, runtime_revision=7, token_sequence=14,
        credential_path=tmp_path / "worker.dpapi", state_command=["state"], transport_command=["transport"],
        occurred_at="2026-10-04T00:00:00Z",
    )
    calls = []
    monkeypatch.delenv("SLK_DSH_SESSION_ID", raising=False)
    monkeypatch.delenv("SLK_DSH_INSTANCE_ID", raising=False)
    monkeypatch.setattr(wc, "_execute_worker_suffix", lambda value: calls.append("suffix") or {
        "status": "CHECKER_DELIVERY_READY", "run_id": value["run_id"],
        "source_message_id": value["source_message_id"],
    }, raising=False)
    monkeypatch.setattr(wc, "_activate_staged_checker", lambda stage, value: calls.append("start") or {
        "status": "CHECKER_STARTED", "candidate_message_id": wc._stable_id(value["source_message_id"], "candidate-ready"),
    })
    result = wc.execute_worker_host_continuation(request)
    assert result["status"] == "CHECKER_STARTED"
    assert calls == ["suffix", "start"]
    # Re-entering the exact host suffix does not replay a known start.
    assert wc.execute_worker_host_continuation(request) == result
    assert calls == ["suffix", "start"]
    altered = {**request, "worker_session_id": "session-another"}
    with pytest.raises(wc.CompletionError):
        wc.execute_worker_host_continuation(altered)
