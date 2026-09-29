import json
import hashlib
import os
from pathlib import Path
import sqlite3
import subprocess

import pytest


def state_binary() -> Path:
    configured = os.environ.get("SLK_STATE_BIN")
    if configured:
        path = Path(configured)
    else:
        suffix = ".exe" if os.name == "nt" else ""
        path = Path(__file__).parents[2] / "target" / "debug" / f"slk-state{suffix}"
    if not path.is_file():
        pytest.skip("build slk-state or set SLK_STATE_BIN before CLI contract tests")
    return path


def invoke(arguments, environment, check=True):
    completed = subprocess.run(
        [str(state_binary()), *map(str, arguments)],
        env=environment,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
    )
    if check and completed.returncode != 0:
        raise AssertionError(completed.stderr)
    return completed


def configured_environment(tmp_path):
    environment = os.environ.copy()
    environment["SLK_CONFIG_PATH"] = str(tmp_path / "config" / "config.json")
    environment.pop("SLK_ROLE_CREDENTIAL", None)
    environment.pop("SLK_OVERWATCHER_CREDENTIAL", None)
    return environment


def write_json(path, value):
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def test_state_cli_reports_the_exact_build_version(tmp_path):
    result = json.loads(invoke(["--version"], configured_environment(tmp_path)).stdout)
    assert result == {"status": "ok", "version": "4.3.2"}


def init_request():
    return {
        "project": {
            "project_id": "project-a",
            "name": "Project A",
            "repository_url": None,
            "last_known_path": "D:/ProjectA",
        },
        "run_id": "run-a",
        "goal": "Goal",
        "boundaries": {},
        "go_nodes": [
            {
                "go_id": "GO-001",
                "ordinal": 1,
                "title": "GO",
                "objective": "Objective",
            }
        ],
        "cell_nodes": [
            {
                "go_id": "GO-001",
                "cell_id": "CELL-001",
                "ordinal": 1,
                "title": "CELL",
                "objective": "Objective",
            }
        ],
        "supervisor": {
            "role_instance_id": "supervisor-a",
            "role": "supervisor",
            "agent_runtime": "codex",
            "provider": "openai",
            "model": "gpt-5.6-sol",
            "reasoning": "xhigh",
            "session_id": "thread-a",
        },
        "supervisor_endpoint": {
            "endpoint_version": 1,
            "transport_adapter": "codex-app-server",
            "host_identity": "host-a",
            "session_id": "thread-a",
            "native_address": {"thread_id": "thread-a"},
        },
        "occurred_at": "2026-09-20T00:00:00Z",
    }


def supervisor_event():
    return {
        "event_id": "d2-started",
        "run_id": "run-a",
        "go_id": None,
        "cell_id": None,
        "attempt": None,
        "plan_revision": 1,
        "role_instance_id": "supervisor-a",
        "event_type": "D2_STARTED",
        "details": {},
        "occurred_at": "2026-09-20T00:00:01Z",
    }


def role_request(event_id, role_instance_id, role):
    if role == "checker":
        runtime, provider, model, adapter = (
            "ocrv",
            "dashscope-tokenplan",
            "qwen3.8-max",
            "ocrv-checker",
        )
    else:
        runtime, provider, model, adapter = (
            "dsh",
            "deepseek",
            "deepseek-v4-flash",
            "dsh-worker",
        )
    session_id = f"session-{role_instance_id}"
    return {
        "event_id": event_id,
        "run_id": "run-a",
        "identity": {
            "role_instance_id": role_instance_id,
            "role": role,
            "agent_runtime": runtime,
            "provider": provider,
            "model": model,
            "reasoning": "provider-default",
            "session_id": session_id,
        },
        "endpoint": {
            "endpoint_version": 1,
            "transport_adapter": adapter,
            "host_identity": "host-a",
            "session_id": session_id,
            "native_address": {"session_id": session_id},
        },
        "occurred_at": "2026-09-20T00:00:01Z",
    }


def close_role_request(event_id, role_instance_id, role):
    return {
        "event_id": event_id,
        "run_id": "run-a",
        "role_instance_id": role_instance_id,
        "role": role,
        "reason": "terminal Run member retirement",
        "occurred_at": "2026-09-20T00:00:03Z",
    }


def overwatcher_binding():
    return {
        "event_id": "bind-overwatcher-a",
        "run_id": "run-a",
        "identity": {
            "role_instance_id": "overwatcher-a",
            "role": "overwatcher",
            "agent_runtime": "codex",
            "provider": "openai",
            "model": "gpt-5.6-sol",
            "reasoning": "xhigh",
            "session_id": "thread-overwatcher-a",
        },
        "endpoint": {
            "endpoint_version": 1,
            "transport_adapter": "codex-app-server",
            "host_identity": "host-a",
            "session_id": "thread-overwatcher-a",
            "native_address": {"thread_id": "thread-overwatcher-a"},
        },
        "observation_mode": "FOREGROUND_ACTIVE_TURN",
        "cadence_seconds": 240,
        "foreground_turn_id": "foreground-turn-a",
        "native_active_session_evidence_ref": "codex:thread-active:overwatcher-a",
        "binding_revision": 1,
        "canonical_task_id": "task-overwatcher-a",
        "reason": "one optional dedicated observer",
        "occurred_at": "2026-09-20T00:00:01Z",
    }


def observation():
    return {
        "observation_id": "observation-a",
        "run_id": "run-a",
        "go_id": "GO-001",
        "cell_id": "CELL-001",
        "attempt": 1,
        "plan_revision": 1,
        "role_instance_id": "overwatcher-a",
        "kind": "ACTIVITY_UNPROVEN",
        "related_event_id": None,
        "message_id": "message-a",
        "evidence_refs": ["transport/message-a/attempt.json"],
        "details": {"reason": "no fresh native execution evidence"},
        "occurred_at": "2026-09-20T00:00:02Z",
    }


def overwatch_cycle(tmp_path):
    state_evidence = tmp_path / "state-revision-2.json"
    native_evidence = tmp_path / "foreground-turn-a.json"
    state_evidence.write_bytes(b'{"runtime_revision":2}')
    native_evidence.write_bytes(b'{"native_liveness":"IN_PROGRESS"}')

    def evidence(path):
        return {
            "path": str(path.resolve()),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }

    return {
        "cycle_id": "cycle-1",
        "run_id": "run-a",
        "plan_revision": 1,
        "role_instance_id": "overwatcher-a",
        "session_id": "thread-overwatcher-a",
        "foreground_turn_id": "foreground-turn-a",
        "binding_revision": 1,
        "runtime_revision": 2,
        "native_liveness": "IN_PROGRESS",
        "cycle_sequence": 1,
        "cadence_seconds": 240,
        "go_id": "GO-001",
        "cell_id": "CELL-001",
        "attempt": 1,
        "token_sequence": 1,
        "token_holder_role_instance_id": "supervisor-a",
        "latest_event_id": "bind-overwatcher-a",
        "latest_message_id": None,
        "checklist": {
            "run_position": "CLEAR",
            "role_bindings": "CLEAR",
            "direct_handoffs": "CLEAR",
            "cell_lifecycle": "CLEAR",
            "stall_and_duplicates": "CLEAR",
            "bi_projection": "CLEAR",
            "active_session": "CLEAR",
            "terminal_closure": "NOT_APPLICABLE",
        },
        "anomaly_codes": [],
        "evidence_refs": [
            evidence(state_evidence),
            evidence(native_evidence),
        ],
        "cost_metrics": None,
        "native_active_session_evidence_ref": str(native_evidence.resolve()),
        "started_at": "2026-09-20T00:03:59Z",
        "completed_at": "2026-09-20T00:04:00Z",
        "next_cycle_at": "2026-09-20T00:08:00Z",
    }


def test_writer_configures_initializes_and_applies_one_role_event(tmp_path):
    environment = configured_environment(tmp_path)
    data_root = tmp_path / "state"
    configured = invoke(["configure", "--data-root", data_root], environment)
    assert json.loads(configured.stdout)["status"] == "configured"

    request_path = write_json(tmp_path / "init.json", init_request())
    initialized = json.loads(
        invoke(["init-run", "--request", request_path], environment).stdout
    )
    credential = initialized["supervisor_credential"]
    assert credential.startswith("slk_")

    event_path = write_json(tmp_path / "event.json", supervisor_event())
    role_environment = environment.copy()
    role_environment["SLK_ROLE_CREDENTIAL"] = credential
    result = json.loads(
        invoke(["write", "--request", event_path], role_environment).stdout
    )
    assert result["status"] == "recorded"


def test_close_role_cli_retires_exact_terminal_checker_and_worker(tmp_path):
    environment = configured_environment(tmp_path)
    data_root = tmp_path / "state"
    invoke(["configure", "--data-root", data_root], environment)
    initialized = json.loads(
        invoke(
            ["init-run", "--request", write_json(tmp_path / "init.json", init_request())],
            environment,
        ).stdout
    )
    supervisor_environment = environment.copy()
    supervisor_environment["SLK_ROLE_CREDENTIAL"] = initialized[
        "supervisor_credential"
    ]
    checker = json.loads(
        invoke(
            [
                "register-role",
                "--request",
                write_json(
                    tmp_path / "checker.json",
                    role_request("register-checker", "checker-a", "checker"),
                ),
            ],
            supervisor_environment,
        ).stdout
    )
    checker_environment = environment.copy()
    checker_environment["SLK_ROLE_CREDENTIAL"] = checker["role_credential"]
    worker = json.loads(
        invoke(
            [
                "register-role",
                "--request",
                write_json(
                    tmp_path / "worker.json",
                    role_request("register-worker", "worker-a", "worker"),
                ),
            ],
            checker_environment,
        ).stdout
    )

    closed = supervisor_event()
    closed.update(
        {
            "event_id": "run-closed",
            "event_type": "RUN_CLOSED",
            "occurred_at": "2026-09-20T00:00:02Z",
        }
    )
    invoke(
        ["write", "--request", write_json(tmp_path / "closed.json", closed)],
        supervisor_environment,
    )

    for role in ("worker", "checker"):
        role_id = f"{role}-a"
        request_path = write_json(
            tmp_path / f"close-{role}.json",
            close_role_request(f"close-{role}", role_id, role),
        )
        result = json.loads(
            invoke(["close-role", "--request", request_path], supervisor_environment).stdout
        )
        assert result["status"] == "closed"
        assert result["role_instance_id"] == role_id
        if role == "worker":
            replay = json.loads(
                invoke(
                    ["close-role", "--request", request_path], supervisor_environment
                ).stdout
            )
            assert replay["status"] == "already_closed"

    with sqlite3.connect(data_root / "slk.db") as database:
        roles = database.execute(
            "SELECT role, lifecycle, successor_role_instance_id FROM role_instances WHERE role IN ('checker','worker') ORDER BY role"
        ).fetchall()
        endpoints = database.execute(
            "SELECT state FROM role_endpoints WHERE role_instance_id IN ('checker-a','worker-a')"
        ).fetchall()
        token = database.execute(
            "SELECT token_sequence, to_role_instance_id FROM token_events ORDER BY token_sequence DESC LIMIT 1"
        ).fetchone()
    assert roles == [("checker", "exited", None), ("worker", "exited", None)]
    assert endpoints == [("retired",), ("retired",)]
    assert token == (1, "supervisor-a")

    worker_environment = environment.copy()
    worker_environment["SLK_ROLE_CREDENTIAL"] = worker["role_credential"]
    rejected = invoke(
        [
            "authenticate-role",
            "--run-id",
            "run-a",
            "--role-instance-id",
            "worker-a",
        ],
        worker_environment,
        check=False,
    )
    assert rejected.returncode != 0


def test_authenticate_role_is_read_only_exact_and_does_not_emit_the_secret(tmp_path):
    environment = configured_environment(tmp_path)
    invoke(["configure", "--data-root", tmp_path / "state"], environment)
    initialized = json.loads(
        invoke(
            ["init-run", "--request", write_json(tmp_path / "init.json", init_request())],
            environment,
        ).stdout
    )
    credential = initialized["supervisor_credential"]
    role_environment = environment.copy()
    role_environment["SLK_ROLE_CREDENTIAL"] = credential
    authenticated = invoke(
        [
            "authenticate-role",
            "--run-id",
            "run-a",
            "--role-instance-id",
            "supervisor-a",
        ],
        role_environment,
    )
    value = json.loads(authenticated.stdout)
    assert value["status"] == "authenticated"
    assert value["role"] == "supervisor"
    assert value["role_instance_id"] == "supervisor-a"
    assert value["runtime_revision"] >= 1
    assert credential not in authenticated.stdout

    rejected = invoke(
        [
            "authenticate-role",
            "--run-id",
            "run-a",
            "--role-instance-id",
            "worker-a",
        ],
        role_environment,
        check=False,
    )
    assert rejected.returncode != 0


def test_writer_has_no_owner_or_anonymous_write_mode(tmp_path):
    environment = configured_environment(tmp_path)
    data_root = tmp_path / "state"
    invoke(["configure", "--data-root", data_root], environment)
    request_path = write_json(tmp_path / "init.json", init_request())
    invoke(["init-run", "--request", request_path], environment)
    event_path = write_json(tmp_path / "event.json", supervisor_event())

    result = invoke(["write", "--request", event_path], environment, check=False)
    assert result.returncode != 0
    error = json.loads(result.stderr)
    assert error["code"] == "SLK_ROLE_CREDENTIAL_REQUIRED"
    assert "SLK_ROLE_CREDENTIAL" in error["message"]


def test_overwatcher_cli_uses_a_separate_observation_credential(tmp_path):
    environment = configured_environment(tmp_path)
    invoke(["configure", "--data-root", tmp_path / "state"], environment)
    initialized = json.loads(
        invoke(
            ["init-run", "--request", write_json(tmp_path / "init.json", init_request())],
            environment,
        ).stdout
    )
    supervisor_environment = environment.copy()
    supervisor_environment["SLK_ROLE_CREDENTIAL"] = initialized["supervisor_credential"]
    bound = json.loads(
        invoke(
            [
                "bind-overwatcher",
                "--request",
                write_json(tmp_path / "overwatcher.json", overwatcher_binding()),
            ],
            supervisor_environment,
        ).stdout
    )
    assert bound["status"] == "overwatcher_bound"

    observer_environment = environment.copy()
    observer_environment["SLK_OVERWATCHER_CREDENTIAL"] = bound[
        "overwatcher_write_credential"
    ]
    cycle = json.loads(
        invoke(
            [
                "record-overwatch-cycle",
                "--request",
                write_json(tmp_path / "cycle.json", overwatch_cycle(tmp_path)),
            ],
            observer_environment,
        ).stdout
    )
    assert cycle == {
        "cycle_id": "cycle-1",
        "cycle_sequence": 1,
        "run_id": "run-a",
        "status": "overwatch_cycle_recorded",
    }
    recorded = json.loads(
        invoke(
            [
                "record-observation",
                "--request",
                write_json(tmp_path / "observation.json", observation()),
            ],
            observer_environment,
        ).stdout
    )
    assert recorded == {
        "observation_id": "observation-a",
        "run_id": "run-a",
        "status": "observation_recorded",
    }

    rejected = invoke(
        ["write", "--request", write_json(tmp_path / "event.json", supervisor_event())],
        observer_environment,
        check=False,
    )
    assert rejected.returncode != 0
    assert json.loads(rejected.stderr)["code"] == "SLK_ROLE_CREDENTIAL_REQUIRED"


def test_overwatcher_credential_rotation_uses_unambiguous_one_time_fields(tmp_path):
    environment = configured_environment(tmp_path)
    invoke(["configure", "--data-root", tmp_path / "state"], environment)
    initialized = json.loads(
        invoke(
            ["init-run", "--request", write_json(tmp_path / "init.json", init_request())],
            environment,
        ).stdout
    )
    supervisor_environment = environment.copy()
    supervisor_environment["SLK_ROLE_CREDENTIAL"] = initialized["supervisor_credential"]
    bound = json.loads(
        invoke(
            [
                "bind-overwatcher",
                "--request",
                write_json(tmp_path / "overwatcher.json", overwatcher_binding()),
            ],
            supervisor_environment,
        ).stdout
    )
    assert "overwatcher_credential" not in bound
    assert "credential_id" not in bound
    assert bound["overwatcher_write_credential"].startswith("slk_")
    assert bound["overwatcher_credential_id"].startswith("credential-")
    assert bound["write_credential_delivery"] == "ONE_TIME_NON_REPLAYABLE"

    evidence = tmp_path / "credential-loss.json"
    evidence.write_bytes(b"credential id was stored instead of secret")
    request = {
        "rotation_id": "rotate-overwatcher-credential-a",
        "run_id": "run-a",
        "expected_binding_revision": 1,
        "expected_runtime_revision": 2,
        "role_instance_id": "overwatcher-a",
        "session_id": "thread-overwatcher-a",
        "foreground_turn_id": "foreground-turn-a",
        "expected_overwatcher_credential_id": bound["overwatcher_credential_id"],
        "evidence": {
            "path": str(evidence.resolve()),
            "sha256": hashlib.sha256(evidence.read_bytes()).hexdigest(),
        },
        "reason": "restore the exact active binding after one-time credential loss",
        "occurred_at": "2026-09-24T00:00:00Z",
    }
    rotated = json.loads(
        invoke(
            [
                "rotate-overwatcher-credential",
                "--request",
                write_json(tmp_path / "rotate.json", request),
            ],
            supervisor_environment,
        ).stdout
    )
    assert rotated["status"] == "overwatcher_credential_rotated"
    assert rotated["binding_revision"] == 1
    assert rotated["runtime_revision"] == 3
    assert rotated["overwatcher_role_instance_id"] == "overwatcher-a"
    assert rotated["overwatcher_credential_id"] != bound["overwatcher_credential_id"]
    assert rotated["overwatcher_write_credential"].startswith("slk_")
    assert rotated["write_credential_delivery"] == "ONE_TIME_NON_REPLAYABLE"

    authenticate_environment = environment.copy()
    authenticate_environment["SLK_ROLE_CREDENTIAL"] = rotated[
        "overwatcher_write_credential"
    ]
    authenticated = json.loads(
        invoke(
            [
                "authenticate-role",
                "--run-id",
                "run-a",
                "--role-instance-id",
                "overwatcher-a",
            ],
            authenticate_environment,
        ).stdout
    )
    assert authenticated["status"] == "authenticated"

    wrong_secret_environment = environment.copy()
    wrong_secret_environment["SLK_ROLE_CREDENTIAL"] = rotated[
        "overwatcher_credential_id"
    ]
    rejected = invoke(
        [
            "authenticate-role",
            "--run-id",
            "run-a",
            "--role-instance-id",
            "overwatcher-a",
        ],
        wrong_secret_environment,
        check=False,
    )
    assert rejected.returncode != 0


def test_overwatcher_cli_rejects_passive_binding_and_incomplete_cycle(tmp_path):
    environment = configured_environment(tmp_path)
    invoke(["configure", "--data-root", tmp_path / "state"], environment)
    initialized = json.loads(
        invoke(
            ["init-run", "--request", write_json(tmp_path / "init.json", init_request())],
            environment,
        ).stdout
    )
    supervisor_environment = environment.copy()
    supervisor_environment["SLK_ROLE_CREDENTIAL"] = initialized["supervisor_credential"]

    passive = overwatcher_binding()
    passive["observation_mode"] = "HEARTBEAT"
    rejected = invoke(
        ["bind-overwatcher", "--request", write_json(tmp_path / "passive.json", passive)],
        supervisor_environment,
        check=False,
    )
    assert rejected.returncode != 0

    too_fast = overwatcher_binding()
    too_fast["cadence_seconds"] = 120
    rejected = invoke(
        ["bind-overwatcher", "--request", write_json(tmp_path / "too-fast.json", too_fast)],
        supervisor_environment,
        check=False,
    )
    assert rejected.returncode != 0

    bound = json.loads(
        invoke(
            [
                "bind-overwatcher",
                "--request",
                write_json(tmp_path / "overwatcher.json", overwatcher_binding()),
            ],
            supervisor_environment,
        ).stdout
    )
    observer_environment = environment.copy()
    observer_environment["SLK_OVERWATCHER_CREDENTIAL"] = bound[
        "overwatcher_write_credential"
    ]
    incomplete = overwatch_cycle(tmp_path)
    del incomplete["checklist"]["active_session"]
    rejected = invoke(
        [
            "record-overwatch-cycle",
            "--request",
            write_json(tmp_path / "incomplete-cycle.json", incomplete),
        ],
        observer_environment,
        check=False,
    )
    assert rejected.returncode != 0

    unknown_anomaly = overwatch_cycle(tmp_path)
    unknown_anomaly["checklist"]["active_session"] = "ANOMALY"
    unknown_anomaly["anomaly_codes"] = ["FREE_TEXT_HEARTBEAT_OK"]
    rejected = invoke(
        [
            "record-overwatch-cycle",
            "--request",
            write_json(tmp_path / "unknown-anomaly.json", unknown_anomaly),
        ],
        observer_environment,
        check=False,
    )
    assert rejected.returncode != 0


def administrative_snapshot(database_path, run_id):
    with sqlite3.connect(database_path) as database:
        row = database.execute(
            """SELECT r.project_id, r.slk_version, r.state, r.closure_state,
                      r.archived_at, r.superseded_by_run_id, l.predecessor_run_id
               FROM runs r LEFT JOIN run_lineage l ON l.successor_run_id=r.run_id
               WHERE r.run_id=?""",
            (run_id,),
        ).fetchone()
        event_count = database.execute(
            "SELECT COUNT(*) FROM work_events WHERE run_id=?", (run_id,)
        ).fetchone()[0]
        latest_event_id = database.execute(
            "SELECT event_id FROM work_events WHERE run_id=? ORDER BY rowid DESC LIMIT 1",
            (run_id,),
        ).fetchone()[0]
        token_sequence, holder = database.execute(
            """SELECT token_sequence, to_role_instance_id FROM token_events
               WHERE run_id=? ORDER BY token_sequence DESC LIMIT 1""",
            (run_id,),
        ).fetchone()
        role_count = database.execute(
            "SELECT COUNT(*) FROM role_instances WHERE run_id=?", (run_id,)
        ).fetchone()[0]
        evidence_count = database.execute(
            "SELECT COUNT(*) FROM evidence WHERE run_id=?", (run_id,)
        ).fetchone()[0]
    return {
        "run_id": run_id,
        "project_id": row[0],
        "slk_version": row[1],
        "state": row[2],
        "closure_state": row[3],
        "archived_at": row[4],
        "superseded_by_run_id": row[5],
        "predecessor_run_id": row[6],
        "event_count": event_count,
        "latest_event_id": latest_event_id,
        "token_sequence": token_sequence,
        "token_holder_role_instance_id": holder,
        "role_count": role_count,
        "evidence_count": evidence_count,
    }


def test_admin_cli_reconciles_and_adopts_with_closed_payloads(tmp_path):
    environment = configured_environment(tmp_path)
    data_root = tmp_path / "state"
    invoke(["configure", "--data-root", data_root], environment)

    source_request = init_request()
    source_request["run_id"] = "run-source"
    source_request["supervisor"]["role_instance_id"] = "supervisor-source"
    source_request["supervisor"]["session_id"] = "thread-source"
    source_request["supervisor_endpoint"]["session_id"] = "thread-source"
    source_request["supervisor_endpoint"]["native_address"] = {
        "thread_id": "thread-source"
    }
    invoke(
        ["init-run", "--request", write_json(tmp_path / "source.json", source_request)],
        environment,
    )

    canonical_request = init_request()
    canonical_request["run_id"] = "run-canonical"
    canonical_request["supervisor"]["role_instance_id"] = "supervisor-canonical"
    canonical_request["supervisor"]["session_id"] = "thread-canonical"
    canonical_request["supervisor_endpoint"]["session_id"] = "thread-canonical"
    canonical_request["supervisor_endpoint"]["native_address"] = {
        "thread_id": "thread-canonical"
    }
    canonical = json.loads(
        invoke(
            [
                "init-run",
                "--request",
                write_json(tmp_path / "canonical.json", canonical_request),
            ],
            environment,
        ).stdout
    )
    supervisor_environment = environment.copy()
    supervisor_environment["SLK_ROLE_CREDENTIAL"] = canonical[
        "supervisor_credential"
    ]
    database_path = data_root / "slk.db"
    with sqlite3.connect(database_path) as database:
        database.execute(
            "UPDATE runs SET slk_version='4.2.1', origin_slk_version='4.2.1'"
        )
    owner = {
        "source_thread_id": "owner-thread",
        "message_id": "owner-message",
        "content_sha256": "0123456789abcdef" * 4,
        "decision": "APPROVE_RUN_IDENTITY_RECONCILIATION",
        "occurred_at": "2026-09-22T10:00:00Z",
    }
    reconcile = {
        "receipt_id": "reconcile-cli",
        "canonical_run_id": "run-canonical",
        "canonical_snapshot": administrative_snapshot(database_path, "run-canonical"),
        "source_snapshots": [administrative_snapshot(database_path, "run-source")],
        "owner_authorization": owner,
        "reason": "Owner selected one canonical Run",
        "occurred_at": "2026-09-22T10:01:00Z",
    }
    reconciled = json.loads(
        invoke(
            [
                "reconcile-run-identities",
                "--request",
                write_json(tmp_path / "reconcile.json", reconcile),
            ],
            supervisor_environment,
        ).stdout
    )
    assert reconciled == {
        "canonical_run_id": "run-canonical",
        "receipt_id": "reconcile-cli",
        "status": "applied",
    }

    unknown = dict(reconcile)
    unknown["receipt_id"] = "reconcile-unknown-field"
    unknown["unexpected"] = True
    rejected = invoke(
        [
            "reconcile-run-identities",
            "--request",
            write_json(tmp_path / "unknown.json", unknown),
        ],
        supervisor_environment,
        check=False,
    )
    assert rejected.returncode != 0

    adoption_owner = dict(owner)
    adoption_owner["decision"] = "APPROVE_METHOD_CONTRACT_ADOPTION"
    adoption_owner["message_id"] = "owner-message-adoption"
    adoption = {
        "receipt_id": "adoption-cli",
        "run_id": "run-canonical",
        "expected_snapshot": administrative_snapshot(database_path, "run-canonical"),
        "from_version": "4.2.1",
        "to_version": "4.2.2",
        "owner_authorization": adoption_owner,
        "reconciliation_receipt_id": "reconcile-cli",
        "compatibility": {
            "topology": "PRESERVED",
            "role_bindings": "PRESERVED",
            "token": "PRESERVED",
            "engineering_history": "PRESERVED",
            "overwatcher": "ABSENT",
        },
        "reason": "Adopt 4.2.2 explicitly",
        "occurred_at": "2026-09-22T10:02:00Z",
    }
    adopted = json.loads(
        invoke(
            [
                "adopt-method-contract",
                "--request",
                write_json(tmp_path / "adopt.json", adoption),
            ],
            supervisor_environment,
        ).stdout
    )
    assert adopted == {
        "effective_version": "4.2.2",
        "receipt_id": "adoption-cli",
        "run_id": "run-canonical",
        "status": "applied",
    }
