use std::fs;

use serde_json::json;
use sha2::{Digest, Sha256};

use slk_state_core::auth::StateError;
use slk_state_core::model::{
    BindOverwatcherRequest, CellDefinition, CloseRoleRequest, CommitDeliveryStartRequest,
    DeliveryStartEvidence, EndpointIdentity, EventType, EvidenceReference, GoDefinition,
    InitRunRequest, NativeStartStatus, ObservationMode, ProjectIdentity, RebindSessionRequest,
    RegisterRoleRequest, ReplaceRoleRequest, RevisePlanRequest, ReviseRoleModelRequest, Role,
    RoleIdentity, TokenHandoffRequest, WriteRequest,
};
use slk_state_core::write::StateStore;

#[test]
fn one_run_has_one_monotonic_current_token_and_linear_nodes() {
    let fixture = Fixture::new();
    let token = fixture.store.current_token("run-a").unwrap();
    assert_eq!(token.sequence, 1);
    assert_eq!(token.owner_role_instance_id, "supervisor-a");

    fixture
        .store
        .handoff_token(&fixture.supervisor, handoff(2, "supervisor-a", "checker-a"))
        .unwrap();
    assert!(matches!(
        fixture
            .store
            .handoff_token(&fixture.checker, handoff(2, "checker-a", "worker-a")),
        Err(StateError::TokenSequenceConflict { .. })
    ));
    assert!(matches!(
        fixture
            .store
            .handoff_token(&fixture.checker, handoff(4, "checker-a", "worker-a")),
        Err(StateError::TokenSequenceGap { .. })
    ));
    fixture
        .store
        .handoff_token(&fixture.checker, handoff(3, "checker-a", "worker-a"))
        .unwrap();

    let current = fixture.store.current_token("run-a").unwrap();
    assert_eq!(current.sequence, 3);
    assert_eq!(current.owner_role_instance_id, "worker-a");
}

#[test]
fn accepted_delivery_projects_engineering_attempt_without_replay_regression() {
    let fixture = Fixture::new();
    let db = slk_state_core::schema::open_database(fixture._root.path()).unwrap();
    db.execute("UPDATE runs SET slk_version='4.3.5' WHERE run_id='run-a'", []).unwrap();
    drop(db);
    let first = fixture.revisioned_start_request(
        2, "supervisor-a", "checker-a", "CELL-001", "CELL_ASSIGNMENT", "ocrv-checker",
    );
    fixture.store.commit_delivery_start(&fixture.supervisor, first.clone()).unwrap();
    let projection = fixture.store.query_run("run-a").unwrap();
    assert_eq!(projection.go_nodes[0].cell_nodes[0].attempt, 2);

    let mut next = fixture.revisioned_start_request(
        3, "checker-a", "worker-a", "CELL-001", "WORKER_TASK", "dsh-worker",
    );
    next.attempt = 3;
    let mut rejected = next.clone();
    rejected.expected_runtime_revision += 10;
    assert!(fixture.store.commit_delivery_start(&fixture.checker, rejected).is_err());
    assert_eq!(fixture.store.query_run("run-a").unwrap().go_nodes[0].cell_nodes[0].attempt, 2);
    fixture.store.commit_delivery_start(&fixture.checker, next).unwrap();
    fixture.store.commit_delivery_start(&fixture.supervisor, first).unwrap();
    let projection = fixture.store.query_run("run-a").unwrap();
    assert_eq!(projection.go_nodes[0].cell_nodes[0].attempt, 3);
    assert_eq!(projection.events.iter().filter(|e| e.event_type == "TRANSPORT_STARTED").count(), 2);
}

#[test]
fn current_d2_start_requires_delivered_d2_ready_and_result_requires_real_start() {
    let fixture = Fixture::new();
    let db = slk_state_core::schema::open_database(fixture._root.path()).unwrap();
    db.execute(
        "UPDATE runs SET slk_version='4.4.3' WHERE run_id='run-a'",
        [],
    )
    .unwrap();
    drop(db);
    let mut request = event(
        "d2-forged",
        EventType::D2Started,
        json!({"source_message_id":"accepted-only"}),
    );
    request.role_instance_id = "supervisor-a".into();
    request.go_id = None;
    request.cell_id = None;
    request.attempt = None;
    assert!(fixture
        .store
        .write_event(&fixture.supervisor, request.clone())
        .is_err());
    request.event_type = EventType::D2Passed;
    assert!(fixture
        .store
        .write_event(&fixture.supervisor, request)
        .is_err());

    let fixture = Fixture::new();
    fixture
        .store
        .handoff_token(&fixture.supervisor, handoff(2, "supervisor-a", "checker-a"))
        .unwrap();
    let mut passed = event("d1-passed", EventType::D1Passed, json!({"verdict":"PASS"}));
    passed.role_instance_id = "checker-a".into();
    fixture.store.write_event(&fixture.checker, passed).unwrap();
    let db = slk_state_core::schema::open_database(fixture._root.path()).unwrap();
    db.execute(
        "UPDATE runs SET slk_version='4.4.3' WHERE run_id='run-a'",
        [],
    )
    .unwrap();
    drop(db);
    let mut ready = fixture.revisioned_start_request(
        3,
        "checker-a",
        "supervisor-a",
        "CELL-001",
        "D2_READY",
        "codex-app-server",
    );
    let path = &ready.start_evidence.stored_path;
    let mut native: serde_json::Value = serde_json::from_slice(&fs::read(path).unwrap()).unwrap();
    native["native_task"]["kind"] = json!("codex-turn");
    native["native_task"]["id"] = json!("session-supervisor-a:turn");
    fs::write(path, serde_json::to_vec(&native).unwrap()).unwrap();
    ready.start_evidence.sha256 = format!("{:x}", Sha256::digest(fs::read(path).unwrap()));
    fixture
        .store
        .commit_delivery_start(&fixture.checker, ready.clone())
        .unwrap();
    let calls = fixture.store.query_run("run-a").unwrap().native_invocations;
    assert_eq!(calls.len(), 1);
    assert_eq!(
        calls[0].start_evidence_path,
        ready.start_evidence.stored_path
    );
    let mut started = event(
        "real-d2-start",
        EventType::D2Started,
        json!({
        "source_message_id":ready.message_id, "token_sequence":3,
        "native_start_path":ready.start_evidence.stored_path, "native_start_sha256":ready.start_evidence.sha256,
        "native_task_id":"session-supervisor-a:turn"}),
    );
    started.role_instance_id = "supervisor-a".into();
    started.go_id = None;
    started.cell_id = None;
    started.attempt = None;
    started.occurred_at = "2026-09-20T00:01:00.500000Z".into();
    let mut final_result = started.clone();
    final_result.event_id = "real-d2-pass".into();
    final_result.event_type = EventType::D2Passed;
    final_result.occurred_at = "2026-09-20T00:02:00Z".into();
    final_result.details =
        json!({"source_message_id":ready.message_id, "d2_started_event_id":started.event_id});
    assert!(fixture
        .store
        .write_event(&fixture.supervisor, final_result.clone())
        .is_err());
    fixture
        .store
        .write_event(&fixture.supervisor, started.clone())
        .unwrap();
    let in_progress = fixture.store.query_run("run-a").unwrap();
    assert!(in_progress
        .events
        .iter()
        .any(|e| e.event_type == "D2_STARTED"));
    assert!(!in_progress
        .events
        .iter()
        .any(|e| e.event_type == "D2_PASSED"));
    let public_projection = serde_json::to_value(&in_progress).unwrap();
    let public_start = public_projection["events"]
        .as_array()
        .unwrap()
        .iter()
        .find(|entry| entry["event_id"] == "real-d2-start")
        .unwrap();
    assert_eq!(public_start["plan_revision"], json!(started.plan_revision));
    fixture
        .store
        .write_event(&fixture.supervisor, started.clone())
        .unwrap();
    assert_eq!(
        fixture.store.query_run("run-a").unwrap().runtime_snapshot,
        in_progress.runtime_snapshot
    );
    started.event_id = "different-d2-start".into();
    assert!(fixture
        .store
        .write_event(&fixture.supervisor, started)
        .is_err());
    let mut too_early = final_result.clone();
    too_early.occurred_at = "2026-09-20T00:01:00.499999Z".into();
    assert!(fixture
        .store
        .write_event(&fixture.supervisor, too_early)
        .is_err());
    fixture
        .store
        .write_event(&fixture.supervisor, final_result)
        .unwrap();
    let mut close = event(
        "close-without-stop-proof",
        EventType::RunClosed,
        json!({"outcome":"passed"}),
    );
    close.role_instance_id = "supervisor-a".into();
    close.go_id = None;
    close.cell_id = None;
    close.attempt = None;
    close.occurred_at = "2026-09-20T00:03:00Z".into();
    assert!(fixture
        .store
        .write_event(&fixture.supervisor, close.clone())
        .is_err());
    let terminal = fixture.store.query_run("run-a").unwrap();
    let snapshot = fixture._root.path().join("d2-terminal.json");
    fs::write(&snapshot, serde_json::to_vec(&terminal).unwrap()).unwrap();
    let proof = fixture._root.path().join("close-quiescence.json");
    let db = slk_state_core::schema::open_database(fixture._root.path()).unwrap();
    db.execute(
        "UPDATE runs SET slk_version='4.4.2' WHERE run_id='run-a'",
        [],
    )
    .unwrap();
    fixture
        .store
        .bind_overwatcher(
            &fixture.supervisor,
            BindOverwatcherRequest {
                event_id: "bind-close-ow".into(),
                run_id: "run-a".into(),
                identity: role("overwatcher-a", Role::Overwatcher),
                endpoint: endpoint("session-overwatcher-a"),
                observation_mode: ObservationMode::ForegroundActiveTurn,
                cadence_seconds: 600,
                foreground_turn_id: "close-ow-turn".into(),
                native_active_session_evidence_ref: "codex:active:overwatcher-a".into(),
                binding_revision: 1,
                canonical_task_id: "close-ow-task".into(),
                reason: "Observe only this Run".into(),
                occurred_at: "2026-09-20T00:02:01Z".into(),
            },
        )
        .unwrap();
    db.execute(
        "UPDATE runs SET slk_version='4.4.3' WHERE run_id='run-a'",
        [],
    )
    .unwrap();
    drop(db);
    pause_run(&fixture);
    assert_eq!(
        fixture.store.query_run("run-a").unwrap().summary.state,
        "paused"
    );
    let mut census = json!({"schema_version":"slk.run-quiescence/v1", "run_id":"run-a", "pause_id":"close-proof",
        "runtime_revision":fixture.store.query_run("run-a").unwrap().runtime_snapshot.unwrap().runtime_revision, "status":"QUIESCENT",
        "attempt_roots":[fixture._root.path()], "observed_at":close.occurred_at,
        "inspections":[{"native_start_path":ready.start_evidence.stored_path,"native_start_sha256":ready.start_evidence.sha256,
            "message_id":ready.message_id,"status":"COORDINATING","processes":[]}]});
    // The producer retains native provenance without changing the five core
    // fields consumed by state. Provenance never grants stop authority.
    census["inspections"][0]["native_reader"] = json!({
        "command":["node", "server.mjs"], "plugin_sha256":"a".repeat(64)});
    census["inspections"][0]["native_stop"] = json!({
        "session":{"session_id":"original-session"}, "native_probe":{"coverage":"UNKNOWN"}});
    fs::write(&proof, serde_json::to_vec(&census).unwrap()).unwrap();
    close.details = json!({"outcome":"passed", "terminal_snapshot_path":snapshot,
        "terminal_snapshot_sha256":format!("{:x}", Sha256::digest(fs::read(&snapshot).unwrap())),
        "quiescence_path":proof,"quiescence_sha256":format!("{:x}", Sha256::digest(fs::read(&proof).unwrap())),
        "close_binding_path":snapshot,"close_binding_sha256":format!("{:x}", Sha256::digest(fs::read(&snapshot).unwrap()))});
    assert!(fixture
        .store
        .write_event(&fixture.supervisor, close.clone())
        .is_err());
    // Isolate the central close predicate; authenticated OW close/cycle behavior
    // is exercised through the original entry in the overwatcher test suite.
    let db = slk_state_core::schema::open_database(fixture._root.path()).unwrap();
    db.execute(
        "UPDATE overwatcher_bindings SET lifecycle_state='closed' WHERE run_id='run-a'",
        [],
    )
    .unwrap();
    drop(db);
    for damage in ["missing-core", "unexpected-key", "scalar-provenance"] {
        let mut invalid = census.clone();
        let row = invalid["inspections"][0].as_object_mut().unwrap();
        match damage {
            "missing-core" => { row.remove("processes"); }
            "unexpected-key" => { row.insert("allow_close".into(), json!(true)); }
            _ => { row.insert("native_reader".into(), json!("trust me")); }
        }
        fs::write(&proof, serde_json::to_vec(&invalid).unwrap()).unwrap();
        close.details["quiescence_sha256"] =
            json!(format!("{:x}", Sha256::digest(fs::read(&proof).unwrap())));
        assert!(fixture.store.write_event(&fixture.supervisor, close.clone()).is_err(), "{damage}");
    }
    census["inspections"][0]["processes"] = json!([{"exists":true,"identity_matches":true}]);
    fs::write(&proof, serde_json::to_vec(&census).unwrap()).unwrap();
    close.details["quiescence_sha256"] =
        json!(format!("{:x}", Sha256::digest(fs::read(&proof).unwrap())));
    assert!(fixture
        .store
        .write_event(&fixture.supervisor, close.clone())
        .is_err());
    census["inspections"][0]["processes"] = json!([]);
    fs::write(&proof, serde_json::to_vec(&census).unwrap()).unwrap();
    close.details["quiescence_sha256"] =
        json!(format!("{:x}", Sha256::digest(fs::read(&proof).unwrap())));
    fixture
        .store
        .write_event(&fixture.supervisor, close.clone())
        .unwrap();
    fixture
        .store
        .write_event(&fixture.supervisor, close)
        .unwrap();
    assert_eq!(
        fixture.store.query_run("run-a").unwrap().summary.state,
        "closed"
    );
}

#[test]
fn failed_transport_is_recorded_without_advancing_responsibility() {
    let fixture = Fixture::worker_active();
    let before = fixture.store.current_token("run-a").unwrap();
    fixture
        .store
        .write_event(
            &fixture.worker,
            event(
                "transport-failed",
                EventType::TransportFailed,
                json!({"message_id":"message-a","error":"NATIVE_START_NOT_OBSERVED"}),
            ),
        )
        .unwrap();
    let after = fixture.store.current_token("run-a").unwrap();
    assert_eq!(before, after);
}

fn lifecycle_event(fixture: &Fixture, id: &str, kind: &str, pause_id: &str) -> WriteRequest {
    let mut request = event(
        id,
        serde_json::from_value(json!(kind)).unwrap(),
        json!({
            "pause_id": pause_id,
            "expected_runtime_revision": fixture.store.query_run("run-a").unwrap().runtime_snapshot.unwrap().runtime_revision,
        }),
    );
    request.role_instance_id = "supervisor-a".into();
    request.go_id = None;
    request.cell_id = None;
    request.attempt = None;
    request
}

fn pause_run(fixture: &Fixture) {
    fixture
        .store
        .write_event(
            &fixture.supervisor,
            lifecycle_event(
                fixture,
                "terminal-pause-request",
                "RUN_PAUSE_REQUESTED",
                "terminal-pause",
            ),
        )
        .unwrap();
    let projection = fixture.store.query_run("run-a").unwrap();
    let mut request = lifecycle_event(fixture, "terminal-paused", "RUN_PAUSED", "terminal-pause");
    let rows: Vec<_> = projection.native_invocations.iter().map(|call| json!({
        "native_start_path":call.start_evidence_path, "native_start_sha256":call.start_evidence_sha256,
        "message_id":call.message_id, "status":"STOPPED", "processes":[]})).collect();
    let path = fixture._root.path().join("terminal-pause-proof.json");
    fs::write(&path, serde_json::to_vec(&json!({"schema_version":"slk.run-quiescence/v1", "run_id":"run-a", "pause_id":"terminal-pause",
        "runtime_revision":projection.runtime_snapshot.unwrap().runtime_revision, "status":"QUIESCENT",
        "attempt_roots":[fixture._root.path()], "inspections":rows, "observed_at":request.occurred_at})).unwrap()).unwrap();
    request.details["quiescence_path"] = json!(path);
    request.details["quiescence_sha256"] =
        json!(format!("{:x}", Sha256::digest(fs::read(&path).unwrap())));
    fixture
        .store
        .write_event(&fixture.supervisor, request)
        .unwrap();
}

#[test]
fn paused_terminal_operations_retain_original_supervisor_token_and_close_proofs() {
    for kind in [EventType::RunAbandoned, EventType::RunSuperseded] {
        let fixture = Fixture::new();
        pause_run(&fixture);
        let mut request = event(
            "paused-owner-terminal",
            kind,
            json!({"reason":"Owner replaced the scheme", "superseded_by_run_id":"run-b"}),
        );
        request.role_instance_id = "supervisor-a".into();
        request.go_id = None;
        request.cell_id = None;
        request.attempt = None;
        assert!(fixture
            .store
            .write_event(&fixture.worker, request.clone())
            .is_err());
        fixture
            .store
            .write_event(&fixture.supervisor, request)
            .unwrap();
        let projection = fixture.store.query_run("run-a").unwrap();
        assert_eq!(projection.summary.state, "archived");
        assert!(!projection
            .events
            .iter()
            .any(|event| event.event_type == "D2_PASSED"));
    }
    let fixture = Fixture::new();
    let db = slk_state_core::schema::open_database(fixture._root.path()).unwrap();
    db.execute(
        "UPDATE runs SET slk_version='4.4.3' WHERE run_id='run-a'",
        [],
    )
    .unwrap();
    pause_run(&fixture);
    let mut request = event("paused-close-without-d2", EventType::RunClosed, json!({}));
    request.role_instance_id = "supervisor-a".into();
    request.go_id = None;
    request.cell_id = None;
    request.attempt = None;
    assert!(
        matches!(fixture.store.write_event(&fixture.supervisor, request),
        Err(StateError::WorkEventInvalid(reason)) if reason.contains("D2 PASS"))
    );
    let fixture = Fixture::worker_active();
    pause_run(&fixture);
    let mut request = event(
        "paused-supersede-without-token",
        EventType::RunSuperseded,
        json!({"reason":"Owner decision", "superseded_by_run_id":"run-b"}),
    );
    request.role_instance_id = "supervisor-a".into();
    assert!(matches!(
        fixture.store.write_event(&fixture.supervisor, request),
        Err(StateError::TokenOwnerMismatch { .. })
    ));
}

#[test]
fn supervisor_abandon_is_management_without_stealing_worker_token_or_other_run() {
    for version in ["4.4.4", "4.5.0"] {
        for paused in [false, true] {
            let fixture = Fixture::worker_active();
            if paused {
                pause_run(&fixture);
            } else {
                let request = lifecycle_event(&fixture, "abandon-pause-request", "RUN_PAUSE_REQUESTED", "abandon-pause");
                fixture.store.write_event(&fixture.supervisor, request).unwrap();
            }
            let db = slk_state_core::schema::open_database(fixture._root.path()).unwrap();
            db.execute("UPDATE runs SET slk_version=?1 WHERE run_id='run-a'", [version]).unwrap();
            drop(db);
            let mut other_request = init_request("run-b");
            other_request.supervisor = role("supervisor-b", Role::Supervisor);
            other_request.supervisor_endpoint = endpoint("session-supervisor-b");
            fixture.store.init_run(other_request).unwrap();
            let other_before = serde_json::to_value(fixture.store.query_run("run-b").unwrap()).unwrap();
            let before = fixture.store.query_run("run-a").unwrap();
            let token = fixture.store.current_token("run-a").unwrap();
            assert_eq!(token.owner_role_instance_id, "worker-a");
            let mut request = event("owner-abandon-preparation", EventType::RunAbandoned,
                json!({"reason":"Owner explicitly abandoned preparation; no D2 verdict"}));
            request.role_instance_id = "supervisor-a".into();
            request.go_id = None;
            request.cell_id = None;
            request.attempt = None;
            assert!(matches!(fixture.store.write_event(&fixture.worker, request.clone()),
                Err(StateError::RoleNotAuthorized { .. })));
            fixture.store.write_event(&fixture.supervisor, request.clone()).unwrap();
            let mut wrong_plan = request.clone();
            wrong_plan.event_id = "abandon-wrong-plan".into();
            wrong_plan.plan_revision += 1;
            assert!(matches!(fixture.store.write_event(&fixture.supervisor, wrong_plan),
                Err(StateError::PlanRevisionMismatch { .. })));
            fixture.store.write_event(&fixture.supervisor, request).unwrap();
            let after = fixture.store.query_run("run-a").unwrap();
            assert_eq!(after.summary.state, "archived");
            assert_eq!(after.summary.closure_state, "abandoned");
            assert_eq!(after.summary.archive_reason.as_deref(), Some("abandoned"));
            assert_eq!(after.events.len(), before.events.len() + 1);
            assert!(!after.events.iter().any(|event| event.event_type == "D2_PASSED"));
            assert_eq!(fixture.store.current_token("run-a").unwrap(), token);
            assert_eq!(serde_json::to_value(fixture.store.query_run("run-b").unwrap()).unwrap(), other_before);
        }
    }
}

#[test]
fn pause_request_is_supervisor_only_without_stealing_token_and_fences_new_work() {
    let fixture = Fixture::worker_active();
    let db = slk_state_core::schema::open_database(fixture._root.path()).unwrap();
    db.execute(
        "UPDATE runs SET slk_version='4.4.3' WHERE run_id='run-a'",
        [],
    )
    .unwrap();
    let before = fixture.store.current_token("run-a").unwrap();
    let request = lifecycle_event(&fixture, "pause-request", "RUN_PAUSE_REQUESTED", "pause-1");
    assert!(fixture
        .store
        .write_event(&fixture.worker, request.clone())
        .is_err());
    fixture
        .store
        .write_event(&fixture.supervisor, request.clone())
        .unwrap();
    fixture
        .store
        .write_event(&fixture.supervisor, request)
        .unwrap();
    assert_eq!(fixture.store.current_token("run-a").unwrap(), before);
    assert_eq!(
        fixture.store.query_run("run-a").unwrap().summary.state,
        "pause_requested"
    );
    fixture
        .store
        .write_event(
            &fixture.worker,
            event("saved-d0", EventType::D0Completed, json!({})),
        )
        .unwrap();
    let mut work = event("new-work", EventType::CellDispatched, json!({}));
    work.role_instance_id = "checker-a".into();
    assert!(fixture.store.write_event(&fixture.checker, work).is_err());
    let resume = lifecycle_event(&fixture, "early-resume", "RUN_RESUMED", "pause-1");
    assert!(fixture
        .store
        .write_event(&fixture.supervisor, resume)
        .is_err());
    let paused = lifecycle_event(&fixture, "false-paused", "RUN_PAUSED", "pause-1");
    assert!(fixture
        .store
        .write_event(&fixture.supervisor, paused)
        .is_err());
    assert_eq!(
        fixture.store.query_run("run-a").unwrap().summary.state,
        "pause_requested"
    );
}

#[test]
fn pause_confirmation_requires_complete_fresh_native_census_and_preserves_token() {
    let fixture = Fixture::worker_active();
    let before = fixture.store.current_token("run-a").unwrap();
    fixture
        .store
        .write_event(
            &fixture.supervisor,
            lifecycle_event(&fixture, "request", "RUN_PAUSE_REQUESTED", "p"),
        )
        .unwrap();
    let mut paused = lifecycle_event(&fixture, "paused", "RUN_PAUSED", "p");
    let path = fixture._root.path().join("quiescence.json");
    let mut proof = json!({"schema_version":"slk.run-quiescence/v1", "run_id":"run-a", "pause_id":"p",
        "runtime_revision": fixture.store.query_run("run-a").unwrap().runtime_snapshot.unwrap().runtime_revision,
        "status":"QUIESCENT"});
    fs::write(&path, serde_json::to_vec(&proof).unwrap()).unwrap();
    paused.details["quiescence_path"] = json!(path.to_str().unwrap());
    paused.details["quiescence_sha256"] =
        json!(format!("{:x}", Sha256::digest(fs::read(&path).unwrap())));
    assert!(fixture
        .store
        .write_event(&fixture.supervisor, paused.clone())
        .is_err());
    proof["inspections"] = json!([]);
    proof["attempt_roots"] = json!([fixture._root.path().to_str().unwrap()]);
    proof["observed_at"] = json!(paused.occurred_at);
    fs::write(&path, serde_json::to_vec(&proof).unwrap()).unwrap();
    paused.details["quiescence_sha256"] =
        json!(format!("{:x}", Sha256::digest(fs::read(&path).unwrap())));
    fixture
        .store
        .write_event(&fixture.supervisor, paused.clone())
        .unwrap();
    fixture
        .store
        .write_event(&fixture.supervisor, paused)
        .unwrap();
    assert_eq!(
        fixture.store.query_run("run-a").unwrap().summary.state,
        "paused"
    );
    assert_eq!(fixture.store.current_token("run-a").unwrap(), before);
    assert!(fixture
        .store
        .write_event(
            &fixture.worker,
            event("late-result", EventType::D0Completed, json!({}))
        )
        .is_err());
}

#[test]
fn pause_census_counts_native_turns_without_losing_alias_receipt_coverage() {
    for damage in [None, Some("other-turn"), Some("other-host"), Some("hash"), Some("missing-row")] {
        let fixture = Fixture::worker_active();
        fixture.store.write_event(&fixture.supervisor,
            lifecycle_event(&fixture, "request", "RUN_PAUSE_REQUESTED", "p")).unwrap();
        let mut paused = lifecycle_event(&fixture, "paused", "RUN_PAUSED", "p");
        let mut rows = Vec::new();
        for number in 0..2 {
            let source = fixture._root.path().join(format!("coordinator-{number}"));
            fs::create_dir(&source).unwrap();
            let path = source.join("started.json");
            let turn = if damage == Some("other-turn") && number == 1 { "other" } else { "current" };
            let message = format!("notice-{number}");
            fs::write(&path, serde_json::to_vec(&json!({"run_id":"run-a", "message_id":message,
                "native_task":{"kind":"codex-desktop-turn", "id":format!("thread:{turn}:item-{number}")}})).unwrap()).unwrap();
            let host = if damage == Some("other-host") && number == 1 { "other" } else { "local" };
            fs::write(source.join("endpoint.json"), serde_json::to_vec(&json!({"role":"supervisor", "run_id":"run-a",
                "host_id":host, "address":{"thread_id":"thread", "cwd":fixture._root.path()}})).unwrap()).unwrap();
            let hash = format!("{:x}", Sha256::digest(fs::read(&path).unwrap()));
            let db = slk_state_core::schema::open_database(fixture._root.path()).unwrap();
            db.execute("INSERT INTO transport_start_receipts(transport_receipt_id,run_id,event_id,message_id,go_id,cell_id,attempt,plan_revision,runtime_revision,token_sequence,from_role_instance_id,to_role_instance_id,endpoint_version,payload_type,payload_sha256,evidence_id,evidence_path,evidence_sha256,endpoint_sha256,envelope_sha256,native_status,request_sha256,occurred_at) VALUES(?5,'run-a',?5,?1,'GO-001','CELL-001',1,1,?6,3,'checker-a','supervisor-a',1,'D2_READY',?2,?5,?3,?4,?2,?2,'STARTED',?2,'2026-09-20T00:00:00Z')",
                rusqlite::params![message, "a".repeat(64), path.to_str().unwrap(), hash, format!("receipt-{number}"), number + 100]).unwrap();
            rows.push(json!({"native_start_path":path,"native_start_sha256":if damage == Some("hash") && number == 1 { "0".repeat(64) } else { hash },
                "message_id":message,"status":"COORDINATING","processes":[]}));
        }
        if damage == Some("missing-row") { rows.pop(); }
        let mut proof = json!({"schema_version":"slk.run-quiescence/v1", "run_id":"run-a", "pause_id":"p",
            "runtime_revision":fixture.store.query_run("run-a").unwrap().runtime_snapshot.unwrap().runtime_revision,
            "status":"QUIESCENT", "attempt_roots":[fixture._root.path()], "observed_at":paused.occurred_at, "inspections":rows});
        let historical = fixture._root.path().join("historical-host.json");
        fs::write(&historical, b"{\"run_id\":\"run-a\",\"plan_revision\":1}").unwrap();
        proof["historical_host_refs"] = json!([{"path":historical,
            "sha256":format!("{:x}", Sha256::digest(fs::read(&historical).unwrap()))}]);
        let path = fixture._root.path().join("census.json");
        fs::write(&path, serde_json::to_vec(&proof).unwrap()).unwrap();
        paused.details["quiescence_path"] = json!(path);
        paused.details["quiescence_sha256"] = json!(format!("{:x}", Sha256::digest(fs::read(&path).unwrap())));
        let result = fixture.store.write_event(&fixture.supervisor, paused);
        assert_eq!(result.is_ok(), damage.is_none(), "{damage:?}: {result:?}");
    }
}

#[test]
fn cancel_requested_pause_resumes_without_false_paused_or_token_change() {
    let fixture = Fixture::worker_active();
    let token = fixture.store.current_token("run-a").unwrap();
    let mut other_request = init_request("run-b");
    other_request.supervisor = role("supervisor-b", Role::Supervisor);
    other_request.supervisor_endpoint = endpoint("session-supervisor-b");
    fixture.store.init_run(other_request).unwrap();
    let other_before = serde_json::to_value(fixture.store.query_run("run-b").unwrap()).unwrap();
    fixture.store.write_event(&fixture.supervisor,
        lifecycle_event(&fixture, "requested-cancel-source", "RUN_PAUSE_REQUESTED", "cancel-pause"))
        .unwrap();
    let request = cancel_requested_event(&fixture, "requested-cancel-resume", "cancel-pause");
    fixture.store.write_event(&fixture.supervisor, request.clone()).unwrap();
    fixture.store.write_event(&fixture.supervisor, request).unwrap();
    let projection = fixture.store.query_run("run-a").unwrap();
    assert_ne!(projection.summary.state, "pause_requested");
    assert_ne!(projection.summary.state, "paused");
    assert_eq!(fixture.store.current_token("run-a").unwrap(), token);
    assert!(!projection.events.iter().any(|e| e.event_type == "RUN_PAUSED"));
    assert_eq!(projection.events.iter().filter(|e| e.event_type == "RUN_RESUMED").count(), 1);
    assert!(projection.events.iter().any(|e| e.event_id == "requested-cancel-source"));
    let delayed = lifecycle_event(&fixture, "delayed-paused", "RUN_PAUSED", "cancel-pause");
    assert!(fixture.store.write_event(&fixture.supervisor, delayed).is_err());
    assert_eq!(serde_json::to_value(fixture.store.query_run("run-b").unwrap()).unwrap(), other_before);
}

#[test]
fn cancel_requested_pause_does_not_bypass_identity_revision_or_confirmed_pause() {
    let fixture = Fixture::worker_active();
    fixture.store.write_event(&fixture.supervisor,
        lifecycle_event(&fixture, "cancel-negative-source", "RUN_PAUSE_REQUESTED", "cancel-pause"))
        .unwrap();
    let request = cancel_requested_event(&fixture, "cancel-negative", "cancel-pause");
    assert!(fixture.store.write_event(&fixture.worker, request.clone()).is_err());
    for kind in ["pause", "revision", "run", "marker", "reason", "extra"] {
        let mut invalid = request.clone();
        invalid.event_id = format!("cancel-negative-{kind}");
        match kind {
            "pause" => invalid.details["pause_id"] = json!("not-the-original-pause"),
            "revision" => invalid.details["expected_runtime_revision"] = json!(99999),
            "run" => invalid.run_id = "not-this-run".into(),
            "marker" => invalid.details["cancel_requested"] = json!(false),
            "reason" => invalid.details["reason"] = json!("  "),
            _ => invalid.details["unrelated"] = json!(true),
        }
        assert!(fixture.store.write_event(&fixture.supervisor, invalid).is_err(), "{kind}");
    }
    let no_request = Fixture::worker_active();
    assert!(no_request.store.write_event(&no_request.supervisor,
        cancel_requested_event(&no_request, "cancel-without-request", "cancel-pause")).is_err());
    let confirmed = Fixture::worker_active();
    pause_run(&confirmed);
    assert!(confirmed.store.write_event(&confirmed.supervisor,
        cancel_requested_event(&confirmed, "cancel-confirmed", "pause-1")).is_err());
}

fn cancel_requested_event(fixture: &Fixture, id: &str, pause: &str) -> WriteRequest {
    let mut request = lifecycle_event(fixture, id, "RUN_RESUMED", pause);
    request.details["cancel_requested"] = json!(true);
    request.details["reason"] = json!("Supervisor cancels the unconfirmed request; no pause claimed");
    request
}

#[test]
fn resource_contention_does_not_advance_token_or_count_as_rework() {
    let fixture = Fixture::worker_active();
    fixture
        .store
        .write_event(
            &fixture.worker,
            event("work-started", EventType::WorkStarted, json!({})),
        )
        .unwrap();
    fixture
        .store
        .write_event(
            &fixture.worker,
            event(
                "resource-contended",
                EventType::ResourceContended,
                json!({"resource":"cargo-target","owner":"live-process","attempt":1}),
            ),
        )
        .unwrap();

    assert_eq!(fixture.store.current_token("run-a").unwrap().sequence, 3);
    assert_eq!(
        fixture.store.d1_rework_count("run-a", "CELL-001").unwrap(),
        0
    );
    assert_eq!(
        fixture
            .store
            .current_cell_state("run-a", "CELL-001")
            .unwrap(),
        "working"
    );

    fixture
        .store
        .write_event(
            &fixture.worker,
            event(
                "resource-recovered",
                EventType::ResourceRecovered,
                json!({"resource":"cargo-target","recovery":"isolated-target-dir"}),
            ),
        )
        .unwrap();
    assert_eq!(
        fixture
            .store
            .current_cell_state("run-a", "CELL-001")
            .unwrap(),
        "working"
    );
}

#[test]
fn current_checker_or_supervisor_can_record_resource_recovery_without_moving_the_token() {
    let supervisor_fixture = Fixture::new();
    let mut supervisor_event = event(
        "supervisor-resource-contended",
        EventType::ResourceContended,
        json!({"resource":"release-port","owner":"live-process"}),
    );
    supervisor_event.role_instance_id = "supervisor-a".into();
    supervisor_fixture
        .store
        .write_event(&supervisor_fixture.supervisor, supervisor_event)
        .unwrap();
    assert_eq!(
        supervisor_fixture
            .store
            .current_token("run-a")
            .unwrap()
            .sequence,
        1
    );

    let checker_fixture = Fixture::new();
    checker_fixture
        .store
        .handoff_token(
            &checker_fixture.supervisor,
            handoff(2, "supervisor-a", "checker-a"),
        )
        .unwrap();
    let mut checker_event = event(
        "checker-resource-recovered",
        EventType::ResourceRecovered,
        json!({"resource":"cargo-target","recovery":"isolated-target-dir"}),
    );
    checker_event.role_instance_id = "checker-a".into();
    checker_fixture
        .store
        .write_event(&checker_fixture.checker, checker_event)
        .unwrap();
    assert_eq!(
        checker_fixture
            .store
            .current_token("run-a")
            .unwrap()
            .sequence,
        2
    );
}

#[test]
fn run_closed_updates_the_read_projection_without_moving_the_token() {
    let fixture = Fixture::two_cells();
    let mut closed = event(
        "run-closed",
        EventType::RunClosed,
        json!({"outcome":"passed"}),
    );
    closed.role_instance_id = "supervisor-a".into();
    closed.go_id = None;
    closed.cell_id = None;
    closed.attempt = None;
    fixture
        .store
        .write_event(&fixture.supervisor, closed)
        .unwrap();

    let projection = fixture.store.query_run("run-a").unwrap();
    assert_eq!(projection.summary.state, "closed");
    assert_eq!(projection.summary.closure_state, "closed");
    assert_eq!(
        projection.summary.closed_at.as_deref(),
        Some("2026-09-20T00:00:03Z")
    );
    assert_eq!(fixture.store.current_token("run-a").unwrap().sequence, 1);
}

#[test]
fn terminal_checker_and_worker_close_is_atomic_auditable_and_idempotent() {
    let fixture = Fixture::new();
    close_run(&fixture);
    let token_before = fixture.store.current_token("run-a").unwrap();

    let worker_request = close_role_request("close-worker", "worker-a", Role::Worker);
    let worker_closed = fixture
        .store
        .close_role(&fixture.supervisor, worker_request.clone())
        .unwrap();
    assert_eq!(worker_closed.status, "closed");
    let replayed = fixture
        .store
        .close_role(&fixture.supervisor, worker_request)
        .unwrap();
    assert_eq!(replayed.status, "already_closed");

    fixture
        .store
        .close_role(
            &fixture.supervisor,
            close_role_request("close-checker", "checker-a", Role::Checker),
        )
        .unwrap();

    let projection = fixture.store.query_run("run-a").unwrap();
    for role_id in ["checker-a", "worker-a"] {
        let role = projection
            .roles
            .iter()
            .find(|role| role.role_instance_id == role_id)
            .unwrap();
        assert_eq!(role.lifecycle, "exited");
        assert_eq!(role.display_state, "archived");
        assert_eq!(role.successor_role_instance_id, None);
        assert!(role
            .endpoints
            .iter()
            .all(|endpoint| endpoint.state == "retired"));
        assert!(role.exited_at.is_some());
    }
    assert_eq!(projection.summary.closure_state, "closed");
    assert_eq!(fixture.store.current_token("run-a").unwrap(), token_before);
    assert_eq!(
        projection
            .events
            .iter()
            .filter(|event| event.event_type == "ROLE_CLOSED")
            .count(),
        2
    );
    assert!(matches!(
        slk_state_core::auth::authorize_role(
            &slk_state_core::schema::open_database(fixture._root.path()).unwrap(),
            "run-a",
            &fixture.worker,
        ),
        Err(StateError::CredentialRevoked)
    ));
}

#[test]
fn installed_4211_tool_reconciles_a_terminal_429_role_without_reopening_the_run() {
    let fixture = Fixture::new();
    close_run(&fixture);
    let connection = slk_state_core::schema::open_database(fixture._root.path()).unwrap();
    connection
        .execute(
            "UPDATE runs SET slk_version='4.2.9' WHERE run_id='run-a'",
            [],
        )
        .unwrap();

    fixture
        .store
        .close_role(
            &fixture.supervisor,
            close_role_request("close-legacy-worker", "worker-a", Role::Worker),
        )
        .unwrap();

    let projection = fixture.store.query_run("run-a").unwrap();
    assert_eq!(projection.summary.slk_version, "4.2.9");
    assert_eq!(projection.summary.state, "closed");
    assert_eq!(projection.summary.closure_state, "closed");
    let worker = projection
        .roles
        .iter()
        .find(|role| role.role_instance_id == "worker-a")
        .unwrap();
    assert_eq!(worker.lifecycle, "exited");
    assert_eq!(worker.display_state, "archived");
}

#[test]
fn close_role_fails_closed_for_open_run_wrong_authority_or_invalid_target() {
    let fixture = Fixture::new();
    assert!(matches!(
        fixture.store.close_role(
            &fixture.supervisor,
            close_role_request("close-open-worker", "worker-a", Role::Worker),
        ),
        Err(StateError::RoleCloseInvalid(_))
    ));

    close_run(&fixture);
    assert!(matches!(
        fixture.store.close_role(
            &fixture.checker,
            close_role_request("close-by-checker", "worker-a", Role::Worker),
        ),
        Err(StateError::RoleCloseInvalid(_))
    ));
    assert!(matches!(
        fixture.store.close_role(
            &fixture.supervisor,
            close_role_request("close-wrong-role", "worker-a", Role::Checker),
        ),
        Err(StateError::RoleCloseInvalid(_))
    ));
    assert!(matches!(
        fixture.store.close_role(
            &fixture.supervisor,
            close_role_request("close-supervisor", "supervisor-a", Role::Supervisor),
        ),
        Err(StateError::RoleCloseInvalid(_))
    ));
    let mut invalid_time = close_role_request("close-invalid-time", "worker-a", Role::Worker);
    invalid_time.occurred_at = "not-a-timestamp".into();
    assert!(fixture
        .store
        .close_role(&fixture.supervisor, invalid_time)
        .is_err());
    assert!(matches!(
        fixture.store.close_role(
            &fixture.supervisor,
            CloseRoleRequest {
                run_id: "run-b".into(),
                ..close_role_request("close-wrong-run", "worker-a", Role::Worker)
            },
        ),
        Err(StateError::CredentialInvalid)
    ));
}

#[test]
fn close_role_rejects_token_holder_nonterminal_projection_and_conflicting_replay() {
    let fixture = Fixture::new();
    close_run(&fixture);
    fixture
        .store
        .handoff_token(&fixture.supervisor, handoff(2, "supervisor-a", "checker-a"))
        .unwrap();
    assert!(matches!(
        fixture.store.close_role(
            &fixture.supervisor,
            close_role_request("close-token-holder", "checker-a", Role::Checker),
        ),
        Err(StateError::RoleCloseInvalid(_))
    ));

    let fixture = Fixture::new();
    let connection = slk_state_core::schema::open_database(fixture._root.path()).unwrap();
    connection
        .execute(
            "UPDATE runs SET state='closed', closure_state='closed', closed_at='2026-09-20T00:00:03Z' WHERE run_id='run-a'",
            [],
        )
        .unwrap();
    assert!(matches!(
        fixture.store.close_role(
            &fixture.supervisor,
            close_role_request("close-without-final-event", "worker-a", Role::Worker),
        ),
        Err(StateError::RoleCloseInvalid(_))
    ));

    let fixture = Fixture::new();
    close_run(&fixture);
    let request = close_role_request("close-worker-conflict", "worker-a", Role::Worker);
    fixture
        .store
        .close_role(&fixture.supervisor, request.clone())
        .unwrap();
    let mut changed = request;
    changed.reason = "different content under the same event id".into();
    assert!(matches!(
        fixture.store.close_role(&fixture.supervisor, changed),
        Err(StateError::WorkEventConflict(_))
    ));
}

#[test]
fn multiple_open_slks_may_share_one_project_without_superseding_each_other() {
    let fixture = Fixture::new();
    let mut replacement = init_request("run-b");
    replacement.supervisor = role("supervisor-b", Role::Supervisor);
    replacement.supervisor_endpoint = endpoint("session-supervisor-b");
    replacement.occurred_at = "2026-09-20T01:00:00Z".into();

    fixture.store.init_run(replacement).unwrap();

    let previous = fixture.store.query_run("run-a").unwrap();
    let current = fixture.store.query_run("run-b").unwrap();
    assert_eq!(previous.summary.closure_state, "open");
    assert_eq!(current.summary.closure_state, "open");
}

#[test]
fn explicit_successor_archives_only_its_predecessor_atomically() {
    let fixture = Fixture::new();
    let mut successor = init_request("run-b");
    successor.predecessor_run_id = Some("run-a".into());
    successor.supervisor = role("supervisor-b", Role::Supervisor);
    successor.supervisor_endpoint = endpoint("session-supervisor-b");
    successor.occurred_at = "2026-09-20T01:00:00Z".into();

    fixture.store.init_run(successor).unwrap();

    let predecessor = fixture.store.query_run("run-a").unwrap();
    let current = fixture.store.query_run("run-b").unwrap();
    assert_eq!(predecessor.summary.closure_state, "superseded");
    assert_eq!(
        predecessor.summary.superseded_by_run_id.as_deref(),
        Some("run-b")
    );
    assert_eq!(current.summary.closure_state, "open");
    assert_eq!(
        fixture
            .store
            .list_runs(Some("project-a"))
            .unwrap()
            .iter()
            .filter(|run| run.closure_state == "open")
            .count(),
        1
    );
}

#[test]
fn supervisor_can_explicitly_supersede_a_run_and_archive_it() {
    let fixture = Fixture::new();
    let mut superseded = event(
        "run-superseded",
        EventType::RunSuperseded,
        json!({"superseded_by_run_id":"run-b"}),
    );
    superseded.role_instance_id = "supervisor-a".into();
    superseded.go_id = None;
    superseded.cell_id = None;
    superseded.attempt = None;

    fixture
        .store
        .write_event(&fixture.supervisor, superseded)
        .unwrap();

    let projection = fixture.store.query_run("run-a").unwrap();
    assert_eq!(projection.summary.state, "archived");
    assert_eq!(projection.summary.closure_state, "superseded");
    assert_eq!(
        projection.summary.archive_reason.as_deref(),
        Some("superseded")
    );
    assert_eq!(
        projection.summary.superseded_by_run_id.as_deref(),
        Some("run-b")
    );
}

#[test]
fn supervisor_can_abandon_an_open_run_without_deleting_its_history() {
    let fixture = Fixture::new();
    let mut abandoned = event(
        "run-abandoned",
        EventType::RunAbandoned,
        json!({"reason":"Owner replaced the engineering scheme"}),
    );
    abandoned.role_instance_id = "supervisor-a".into();
    abandoned.go_id = None;
    abandoned.cell_id = None;
    abandoned.attempt = None;

    fixture
        .store
        .write_event(&fixture.supervisor, abandoned)
        .unwrap();

    let projection = fixture.store.query_run("run-a").unwrap();
    assert_eq!(projection.summary.state, "archived");
    assert_eq!(projection.summary.closure_state, "abandoned");
    assert_eq!(
        projection.summary.archive_reason.as_deref(),
        Some("abandoned")
    );
    assert_eq!(
        projection.events.last().unwrap().event_type,
        "RUN_ABANDONED"
    );
}

#[test]
fn session_rebound_retires_the_old_endpoint_and_preserves_the_role_credential() {
    let fixture = Fixture::new();
    let mut wrong_endpoint = endpoint_v("session-checker-rebound", 2);
    wrong_endpoint.transport_adapter = "codex-app-server".into();
    assert!(matches!(
        fixture.store.rebind_session(
            &fixture.supervisor,
            RebindSessionRequest {
                event_id: "rebind-checker-invalid".into(),
                run_id: "run-a".into(),
                role_instance_id: "checker-a".into(),
                endpoint: wrong_endpoint,
                reason: "wrong adapter".into(),
                occurred_at: "2026-09-20T00:00:03Z".into(),
            },
        ),
        Err(StateError::RoleBindingInvalid { .. })
    ));
    fixture
        .store
        .rebind_session(
            &fixture.supervisor,
            RebindSessionRequest {
                event_id: "rebind-checker".into(),
                run_id: "run-a".into(),
                role_instance_id: "checker-a".into(),
                endpoint: endpoint_v("session-checker-rebound", 2),
                reason: "native session resumed elsewhere".into(),
                occurred_at: "2026-09-20T00:00:03Z".into(),
            },
        )
        .unwrap();

    let checker = fixture
        .store
        .query_run("run-a")
        .unwrap()
        .role("checker")
        .unwrap()
        .clone();
    assert_eq!(checker.role_instance_id, "checker-a");
    assert_eq!(checker.session_id, "session-checker-rebound");
    assert!(matches!(
        fixture
            .store
            .handoff_token(&fixture.supervisor, handoff(2, "supervisor-a", "checker-a")),
        Err(StateError::EndpointNotCurrent)
    ));
    let mut rebound_handoff = handoff(2, "supervisor-a", "checker-a");
    rebound_handoff.endpoint_version = 2;
    fixture
        .store
        .handoff_token(&fixture.supervisor, rebound_handoff)
        .unwrap();
}

#[test]
fn a_correction_appends_to_the_original_authored_fact() {
    let fixture = Fixture::worker_active();
    fixture
        .store
        .write_event(
            &fixture.worker,
            event(
                "work-started",
                EventType::WorkStarted,
                json!({"path":"old"}),
            ),
        )
        .unwrap();
    let mut correction = event(
        "work-started-correction",
        EventType::WorkProgress,
        json!({"path":"correct"}),
    );
    correction.corrects_event_id = Some("work-started".into());
    fixture
        .store
        .write_event(&fixture.worker, correction)
        .unwrap();

    let projection = fixture.store.query_run("run-a").unwrap();
    let corrected = projection
        .events
        .iter()
        .find(|item| item.event_id == "work-started-correction")
        .unwrap();
    assert_eq!(corrected.corrects_event_id.as_deref(), Some("work-started"));
}

#[test]
fn plan_revision_and_role_replacement_preserve_current_authority() {
    let fixture = Fixture::new();
    let revision = fixture
        .store
        .revise_plan(
            &fixture.supervisor,
            RevisePlanRequest {
                event_id: "plan-revised".into(),
                run_id: "run-a".into(),
                snapshot: json!({"reason":"split later CELL"}),
                reason: "engineering scheme changed".into(),
                occurred_at: "2026-09-20T00:00:02Z".into(),
            },
        )
        .unwrap();
    assert_eq!(revision, 2);

    let replacement = fixture
        .store
        .replace_role(
            &fixture.supervisor,
            ReplaceRoleRequest {
                event_id: "replace-checker".into(),
                run_id: "run-a".into(),
                old_role_instance_id: "checker-a".into(),
                replacement: role("checker-b", Role::Checker),
                endpoint: endpoint("session-checker-b"),
                reason: "original Checker unavailable".into(),
                occurred_at: "2026-09-20T00:00:03Z".into(),
            },
        )
        .unwrap();
    assert!(matches!(
        slk_state_core::auth::authorize_event(
            &slk_state_core::schema::open_database(fixture._root.path()).unwrap(),
            "run-a",
            &fixture.checker,
            EventType::D1Started
        ),
        Err(StateError::CredentialRevoked)
    ));
    assert_eq!(
        slk_state_core::auth::authorize_event(
            &slk_state_core::schema::open_database(fixture._root.path()).unwrap(),
            "run-a",
            &replacement.credential,
            EventType::D1Started
        )
        .unwrap()
        .role_instance_id,
        "checker-b"
    );
}

#[test]
fn plan_revision_requires_a_substantive_nonempty_change() {
    let fixture = Fixture::new();

    for (event_id, snapshot, reason, expected) in [
        (
            "plan-empty",
            json!({}),
            "empty snapshot",
            "plan revision snapshot must be a non-empty object",
        ),
        (
            "plan-blank-reason",
            json!({"cells":["CELL-001","CELL-002"]}),
            "   ",
            "plan revision reason must not be blank",
        ),
    ] {
        let error = fixture
            .store
            .revise_plan(
                &fixture.supervisor,
                RevisePlanRequest {
                    event_id: event_id.into(),
                    run_id: "run-a".into(),
                    snapshot,
                    reason: reason.into(),
                    occurred_at: "2026-09-20T00:00:02Z".into(),
                },
            )
            .unwrap_err();
        assert_eq!(
            error.to_string(),
            format!("invalid linear plan: {expected}")
        );
    }

    let snapshot = json!({"cells":["CELL-001","CELL-002"]});
    assert_eq!(
        fixture
            .store
            .revise_plan(
                &fixture.supervisor,
                RevisePlanRequest {
                    event_id: "plan-split".into(),
                    run_id: "run-a".into(),
                    snapshot: snapshot.clone(),
                    reason: "split the remaining acceptance surface".into(),
                    occurred_at: "2026-09-20T00:00:02Z".into(),
                },
            )
            .unwrap(),
        2
    );

    let unchanged = fixture
        .store
        .revise_plan(
            &fixture.supervisor,
            RevisePlanRequest {
                event_id: "plan-split-again".into(),
                run_id: "run-a".into(),
                snapshot,
                reason: "repeat the same plan under a new event".into(),
                occurred_at: "2026-09-20T00:00:03Z".into(),
            },
        )
        .unwrap_err();
    assert_eq!(
        unchanged.to_string(),
        "invalid linear plan: plan revision must change the current snapshot"
    );

    assert_eq!(
        fixture
            .store
            .revise_plan(
                &fixture.supervisor,
                RevisePlanRequest {
                    event_id: "plan-split-expanded".into(),
                    run_id: "run-a".into(),
                    snapshot: json!({"cells":["CELL-001","CELL-002","CELL-003"]}),
                    reason: "new capacity evidence requires another split".into(),
                    occurred_at: "2026-09-20T00:00:04Z".into(),
                },
            )
            .unwrap(),
        3
    );
}

#[test]
fn d2_repair_append_preserves_history_and_opens_only_the_next_cell() {
    let fixture = Fixture::new();
    fixture.store.handoff_token(&fixture.supervisor, handoff(2, "supervisor-a", "checker-a")).unwrap();
    let mut passed = event("accepted-before-d2", EventType::D1Passed, json!({"verdict":"PASS"}));
    passed.role_instance_id = "checker-a".into();
    fixture.store.write_event(&fixture.checker, passed).unwrap();
    let mut ready = handoff(3, "checker-a", "supervisor-a");
    ready.payload_type = "D2_READY".into();
    fixture.store.handoff_token(&fixture.checker, ready).unwrap();
    let mut failed = event("original-d2-failure", EventType::D2Failed, json!({"verdict":"FAIL"}));
    failed.role_instance_id = "supervisor-a".into();
    failed.go_id = None;
    failed.cell_id = None;
    failed.attempt = None;
    fixture.store.write_event(&fixture.supervisor, failed).unwrap();
    fixture.store.handoff_token(&fixture.supervisor, handoff(4, "supervisor-a", "checker-a")).unwrap();
    let before = fixture.store.query_run("run-a").unwrap();
    let token_before = fixture.store.current_token("run-a").unwrap();
    let request = RevisePlanRequest {
        event_id: "append-d2-repair".into(), run_id: "run-a".into(),
        snapshot: json!({"expected_plan_revision":1,"d2_repair_cell_append":{
            "source_d2_failed_event_id":"original-d2-failure",
            "cell":{"go_id":"GO-001","cell_id":"CELL-002","ordinal":2,
                    "title":"D2 correction","objective":"Correct the actual composition defect"}
        }}),
        reason: "Owner-approved single corrective CELL after real D2 failure".into(),
        occurred_at: "2026-09-20T00:00:07Z".into(),
    };
    let mut wrong_failure = request.clone();
    wrong_failure.snapshot["d2_repair_cell_append"]["source_d2_failed_event_id"] = json!("accepted-before-d2");
    assert!(fixture.store.revise_plan(&fixture.supervisor, wrong_failure).is_err());
    assert!(fixture.store.revise_plan(&fixture.worker, request.clone()).is_err());
    assert_eq!(fixture.store.revise_plan(&fixture.supervisor, request.clone()).unwrap(), 2);
    let after = fixture.store.query_run("run-a").unwrap();
    assert_eq!(fixture.store.current_token("run-a").unwrap(), token_before);
    assert_eq!(after.go_nodes[0].cell_nodes.len(), 2);
    assert_eq!(after.go_nodes[0].cell_nodes[0].state, "d1_passed");
    assert_eq!(after.go_nodes[0].cell_nodes[0].attempt, before.go_nodes[0].cell_nodes[0].attempt);
    assert_eq!(after.go_nodes[0].cell_nodes[1].state, "planned");
    assert!(before.events.iter().all(|old| after.events.iter().any(|new| new == old)));
    assert!(fixture.store.revise_plan(&fixture.supervisor, request.clone()).is_err());
    let mut again = request;
    again.event_id = "duplicate-or-unaccepted-append".into();
    again.snapshot["expected_plan_revision"] = json!(2);
    assert!(fixture.store.revise_plan(&fixture.supervisor, again).is_err());
    let mut next = handoff(5, "checker-a", "worker-a");
    next.cell_id = "CELL-002".into();
    next.payload_type = "WORKER_TASK".into();
    fixture.store.handoff_token(&fixture.checker, next).unwrap();
    let mut d0 = event("repair-d0", EventType::D0Completed, json!({"verdict":"PASS"}));
    d0.cell_id = Some("CELL-002".into());
    d0.plan_revision = 2;
    fixture.store.write_event(&fixture.worker, d0).unwrap();
    let mut report = handoff(6, "worker-a", "checker-a");
    report.cell_id = "CELL-002".into();
    report.payload_type = "WORKER_REPORT".into();
    fixture.store.handoff_token(&fixture.worker, report).unwrap();
    let mut d1 = event("repair-d1", EventType::D1Passed, json!({"verdict":"PASS"}));
    d1.role_instance_id = "checker-a".into();
    d1.cell_id = Some("CELL-002".into());
    d1.plan_revision = 2;
    fixture.store.write_event(&fixture.checker, d1).unwrap();
    let mut ready = handoff(7, "checker-a", "supervisor-a");
    ready.cell_id = "CELL-002".into();
    ready.payload_type = "D2_READY".into();
    fixture.store.handoff_token(&fixture.checker, ready).unwrap();
    let mut d2 = event("repair-d2", EventType::D2Passed, json!({"verdict":"PASS"}));
    d2.role_instance_id = "supervisor-a".into();
    d2.go_id = None;
    d2.cell_id = None;
    d2.attempt = None;
    d2.plan_revision = 2;
    fixture.store.write_event(&fixture.supervisor, d2).unwrap();
    let final_state = fixture.store.query_run("run-a").unwrap();
    assert!(final_state.go_nodes[0].cell_nodes.iter().all(|cell| cell.state == "d1_passed"));
    assert!(final_state.events.iter().any(|item| item.event_id == "original-d2-failure"));
    assert!(final_state.events.iter().any(|item| item.event_id == "repair-d2"));
}

#[test]
fn token_cannot_skip_the_checker() {
    let fixture = Fixture::new();
    assert!(matches!(
        fixture
            .store
            .handoff_token(&fixture.supervisor, handoff(2, "supervisor-a", "worker-a")),
        Err(StateError::InvalidTokenRoute { .. })
    ));
    assert_eq!(fixture.store.current_token("run-a").unwrap().sequence, 1);
}

#[test]
fn fixed_engineering_role_bindings_fail_closed() {
    let root = tempfile::tempdir().unwrap();
    let store = StateStore::new(root.path());
    let mut invalid_supervisor = init_request("run-a");
    invalid_supervisor.supervisor = role("supervisor-a", Role::Worker);
    assert!(matches!(
        store.init_run(invalid_supervisor),
        Err(StateError::RoleBindingInvalid { .. })
    ));

    let initialized = store.init_run(init_request("run-a")).unwrap();
    let mut invalid_checker = role_request("register-checker", "checker-a", Role::Checker);
    invalid_checker.identity.agent_runtime = "codex".into();
    invalid_checker.identity.provider = "openai".into();
    invalid_checker.identity.model = "gpt-5.6-sol".into();
    invalid_checker.endpoint.transport_adapter = "codex-app-server".into();
    assert!(matches!(
        store.register_role(&initialized.supervisor_credential, invalid_checker),
        Err(StateError::RoleBindingInvalid { .. })
    ));
}

#[test]
fn supervisor_binding_is_exact_61_sol_with_owner_selected_high_or_xhigh() {
    let root = tempfile::tempdir().unwrap();
    let store = StateStore::new(root.path());
    let mut selected = init_request("run-a");
    selected.supervisor.reasoning = "high".into();
    store.init_run(selected).unwrap();

    let root = tempfile::tempdir().unwrap();
    let store = StateStore::new(root.path());
    let mut wrong_class = init_request("run-b");
    wrong_class.supervisor.model = "gpt-5.6-sol".into();
    assert!(matches!(
        store.init_run(wrong_class),
        Err(StateError::RoleBindingInvalid { .. })
    ));
}

#[test]
fn supervisor_model_revision_preserves_identity_and_appends_evidence() {
    let root = tempfile::tempdir().unwrap();
    let store = StateStore::new(root.path());
    let initialized = store.init_run(init_request("run-a")).unwrap();
    let database = rusqlite::Connection::open(root.path().join("slk.db")).unwrap();
    database.execute(
        "UPDATE role_instances SET model='gpt-5.6-sol' WHERE run_id='run-a' AND role='supervisor'",
        [],
    ).unwrap();
    let evidence_path = root.path().join("owner-model-choice.txt");
    std::fs::write(
        &evidence_path,
        b"Owner selected gpt-6.1-sol xhigh for this Run",
    )
    .unwrap();
    let evidence_sha256 = format!(
        "{:x}",
        Sha256::digest(std::fs::read(&evidence_path).unwrap())
    );

    let request = ReviseRoleModelRequest {
        event_id: "model-revised-1".into(),
        run_id: "run-a".into(),
        role_instance_id: "supervisor-a".into(),
        expected_runtime_revision: 1,
        model: "gpt-6.1-sol".into(),
        reasoning: "xhigh".into(),
        owner_evidence: EvidenceReference {
            path: evidence_path.to_string_lossy().into_owned(),
            sha256: evidence_sha256,
        },
        reason: "Owner model policy correction".into(),
        occurred_at: "2026-10-05T00:00:00Z".into(),
    };
    let result = store
        .revise_role_model(&initialized.supervisor_credential, request.clone())
        .unwrap();

    assert_eq!(result.status, "MODEL_REVISED");
    assert_eq!(result.role_instance_id, "supervisor-a");
    assert_eq!(result.previous_model, "gpt-5.6-sol");
    assert_eq!(result.model, "gpt-6.1-sol");
    let row: (String, String, String) = database.query_row(
        "SELECT role_instance_id, model, reasoning FROM role_instances WHERE run_id='run-a' AND role='supervisor'",
        [], |row| Ok((row.get(0)?, row.get(1)?, row.get(2)?)),
    ).unwrap();
    assert_eq!(
        row,
        ("supervisor-a".into(), "gpt-6.1-sol".into(), "xhigh".into())
    );
    let details: String = database
        .query_row(
            "SELECT details_json FROM work_events WHERE event_id='model-revised-1'",
            [],
            |row| row.get(0),
        )
        .unwrap();
    assert!(details.contains("gpt-5.6-sol") && details.contains("gpt-6.1-sol"));
    let replay = store
        .revise_role_model(&initialized.supervisor_credential, request)
        .unwrap();
    assert_eq!(replay.status, "ALREADY_APPLIED");
    assert_eq!(replay.previous_model, "gpt-5.6-sol");
    assert_eq!(replay.runtime_revision, result.runtime_revision);
}

#[test]
fn d1_incomplete_keeps_checker_token_and_cell_open() {
    let fixture = Fixture::new();
    fixture
        .store
        .handoff_token(&fixture.supervisor, handoff(2, "supervisor-a", "checker-a"))
        .unwrap();
    let mut incomplete = event(
        "d1-incomplete",
        EventType::D1Incomplete,
        json!({"unproven":["real target smoke"]}),
    );
    incomplete.role_instance_id = "checker-a".into();
    fixture
        .store
        .write_event(&fixture.checker, incomplete)
        .unwrap();

    let token = fixture.store.current_token("run-a").unwrap();
    assert_eq!(token.owner_role_instance_id, "checker-a");
    assert_eq!(token.sequence, 2);
    assert_eq!(
        fixture
            .store
            .current_cell_state("run-a", "CELL-001")
            .unwrap(),
        "d1_incomplete"
    );
    assert_eq!(
        fixture.store.d1_rework_count("run-a", "CELL-001").unwrap(),
        0
    );
    let mut wrong_escalation = handoff(3, "checker-a", "supervisor-a");
    wrong_escalation.payload_type = "D1_FAILURE_ESCALATION".into();
    assert!(matches!(
        fixture
            .store
            .handoff_token(&fixture.checker, wrong_escalation),
        Err(StateError::InvalidTokenRoute { .. })
    ));
    assert!(matches!(
        fixture
            .store
            .handoff_token(&fixture.checker, handoff(3, "checker-a", "worker-a")),
        Err(StateError::InvalidTokenRoute { .. })
    ));
    let mut management = handoff(3, "checker-a", "supervisor-a");
    management.payload_type = "D1_INCOMPLETE_ESCALATION".into();
    let result = fixture
        .store
        .handoff_token(&fixture.checker, management)
        .unwrap();
    assert_eq!(result.sequence, 3);
    assert_eq!(result.owner_role_instance_id, "supervisor-a");
    let mut unrelated_return = handoff(4, "supervisor-a", "checker-a");
    unrelated_return.payload_type = "TRANSPORT_PROBE".into();
    assert!(matches!(
        fixture
            .store
            .handoff_token(&fixture.supervisor, unrelated_return),
        Err(StateError::InvalidTokenRoute { .. })
    ));
    let mut management_return = handoff(4, "supervisor-a", "checker-a");
    management_return.payload_type = "D1_MANAGEMENT_RETURN".into();
    let returned = fixture
        .store
        .handoff_token(&fixture.supervisor, management_return)
        .unwrap();
    assert_eq!(returned.sequence, 4);
    assert_eq!(returned.owner_role_instance_id, "checker-a");
    assert_eq!(
        fixture.store.d1_rework_count("run-a", "CELL-001").unwrap(),
        0
    );
}

#[test]
fn supervisor_to_worker_is_only_valid_after_current_d1_fail_escalation() {
    let fixture = Fixture::new();
    fixture
        .store
        .handoff_token(&fixture.supervisor, handoff(2, "supervisor-a", "checker-a"))
        .unwrap();

    let mut premature = handoff(3, "checker-a", "supervisor-a");
    premature.payload_type = "D1_FAILURE_ESCALATION".into();
    assert!(matches!(
        fixture.store.handoff_token(&fixture.checker, premature),
        Err(StateError::InvalidTokenRoute { .. })
    ));

    let mut wrong_owner = handoff(3, "checker-a", "worker-a");
    wrong_owner.payload_type = "D1_REWORK_DIRECTIVE".into();
    assert!(matches!(
        fixture.store.handoff_token(&fixture.checker, wrong_owner),
        Err(StateError::InvalidTokenRoute { .. })
    ));

    let fixture = Fixture::new();
    fixture
        .store
        .handoff_token(&fixture.supervisor, handoff(2, "supervisor-a", "checker-a"))
        .unwrap();
    for (event_id, event_type) in [
        ("d1-failed-stale", EventType::D1Failed),
        ("d1-incomplete-current", EventType::D1Incomplete),
    ] {
        let mut observation = event(event_id, event_type, json!({"evidence":[event_id]}));
        observation.role_instance_id = "checker-a".into();
        fixture
            .store
            .write_event(&fixture.checker, observation)
            .unwrap();
    }
    let mut escalation = handoff(3, "checker-a", "supervisor-a");
    escalation.payload_type = "D1_FAILURE_ESCALATION".into();
    assert!(matches!(
        fixture.store.handoff_token(&fixture.checker, escalation),
        Err(StateError::InvalidTokenRoute { .. })
    ));

    let fixture = Fixture::new();
    fixture
        .store
        .handoff_token(&fixture.supervisor, handoff(2, "supervisor-a", "checker-a"))
        .unwrap();
    let mut failed = event(
        "d1-failed",
        EventType::D1Failed,
        json!({"candidate_sha256":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}),
    );
    failed.role_instance_id = "checker-a".into();
    fixture.store.write_event(&fixture.checker, failed).unwrap();
    assert!(matches!(
        fixture
            .store
            .handoff_token(&fixture.checker, handoff(3, "checker-a", "worker-a")),
        Err(StateError::InvalidTokenRoute { .. })
    ));
    let mut escalation = handoff(3, "checker-a", "supervisor-a");
    escalation.payload_type = "D1_FAILURE_ESCALATION".into();
    fixture
        .store
        .handoff_token(&fixture.checker, escalation)
        .unwrap();

    let mut rework_requested = event(
        "rework-requested-1",
        EventType::ReworkRequested,
        json!({
            "d1_failure_event_id":"d1-failed",
            "failed_candidate_sha256":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            "rework_round":1
        }),
    );
    rework_requested.role_instance_id = "supervisor-a".into();
    fixture
        .store
        .write_event(&fixture.supervisor, rework_requested)
        .unwrap();

    let mut wrong_payload = handoff(4, "supervisor-a", "worker-a");
    wrong_payload.payload_type = "CELL_ASSIGNMENT".into();
    assert!(matches!(
        fixture
            .store
            .handoff_token(&fixture.supervisor, wrong_payload),
        Err(StateError::InvalidTokenRoute { .. })
    ));

    let mut wrong_cell = handoff(4, "supervisor-a", "worker-a");
    wrong_cell.payload_type = "D1_REWORK_DIRECTIVE".into();
    wrong_cell.cell_id = "CELL-OTHER".into();
    assert!(matches!(
        fixture.store.handoff_token(&fixture.supervisor, wrong_cell),
        Err(StateError::InvalidTokenRoute { .. })
    ));

    let mut directive = handoff(4, "supervisor-a", "worker-a");
    directive.payload_type = "D1_REWORK_DIRECTIVE".into();
    let current = fixture
        .store
        .handoff_token(&fixture.supervisor, directive)
        .unwrap();
    assert_eq!(current.owner_role_instance_id, "worker-a");
    assert_eq!(current.sequence, 4);
}

#[test]
fn checker_d1_pass_routes_only_to_next_work_or_final_d2_ready() {
    let fixture = Fixture::new();
    fixture
        .store
        .handoff_token(&fixture.supervisor, handoff(2, "supervisor-a", "checker-a"))
        .unwrap();
    let mut passed = event("d1-passed", EventType::D1Passed, json!({"verdict":"PASS"}));
    passed.role_instance_id = "checker-a".into();
    fixture.store.write_event(&fixture.checker, passed).unwrap();

    for (to, payload_type) in [
        ("worker-a", "CELL_ASSIGNMENT"),
        ("worker-a", "D2_READY"),
        ("supervisor-a", "WORKER_TASK"),
        ("supervisor-a", "CELL_ASSIGNMENT"),
    ] {
        let mut invalid = handoff(3, "checker-a", to);
        invalid.payload_type = payload_type.into();
        assert!(matches!(
            fixture.store.handoff_token(&fixture.checker, invalid),
            Err(StateError::InvalidTokenRoute { .. })
        ));
    }

    let mut final_ready = handoff(3, "checker-a", "supervisor-a");
    final_ready.payload_type = "D2_READY".into();
    fixture
        .store
        .handoff_token(&fixture.checker, final_ready)
        .unwrap();

    let fixture = Fixture::two_cells();
    fixture
        .store
        .handoff_token(&fixture.supervisor, handoff(2, "supervisor-a", "checker-a"))
        .unwrap();
    let mut passed = event("d1-passed", EventType::D1Passed, json!({"verdict":"PASS"}));
    passed.role_instance_id = "checker-a".into();
    fixture.store.write_event(&fixture.checker, passed).unwrap();
    let mut next = handoff(3, "checker-a", "worker-a");
    next.cell_id = "CELL-002".into();
    next.payload_type = "WORKER_TASK".into();
    fixture.store.handoff_token(&fixture.checker, next).unwrap();
}

#[test]
fn rework_request_fails_closed_for_wrong_authority_identity_candidate_attempt_or_round() {
    let fixture = Fixture::new();
    fixture
        .store
        .handoff_token(&fixture.supervisor, handoff(2, "supervisor-a", "checker-a"))
        .unwrap();

    let mut checker_authored = event(
        "checker-rework",
        EventType::ReworkRequested,
        json!({
            "d1_failure_event_id":"d1-failed",
            "failed_candidate_sha256":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            "rework_round":1
        }),
    );
    checker_authored.role_instance_id = "checker-a".into();
    assert!(matches!(
        fixture
            .store
            .write_event(&fixture.checker, checker_authored),
        Err(StateError::RoleNotAuthorized { .. })
    ));

    let mut failed = event(
        "d1-failed",
        EventType::D1Failed,
        json!({"candidate_sha256":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}),
    );
    failed.role_instance_id = "checker-a".into();
    fixture.store.write_event(&fixture.checker, failed).unwrap();
    let mut escalation = handoff(3, "checker-a", "supervisor-a");
    escalation.payload_type = "D1_FAILURE_ESCALATION".into();
    fixture
        .store
        .handoff_token(&fixture.checker, escalation)
        .unwrap();

    for (event_id, failure_id, candidate, attempt, round) in [
        (
            "wrong-failure",
            "d1-other",
            "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            1,
            1,
        ),
        (
            "wrong-candidate",
            "d1-failed",
            "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
            1,
            1,
        ),
        (
            "wrong-attempt",
            "d1-failed",
            "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            2,
            1,
        ),
        (
            "wrong-round",
            "d1-failed",
            "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            1,
            2,
        ),
    ] {
        let mut request = event(
            event_id,
            EventType::ReworkRequested,
            json!({
                "d1_failure_event_id":failure_id,
                "failed_candidate_sha256":candidate,
                "rework_round":round
            }),
        );
        request.role_instance_id = "supervisor-a".into();
        request.attempt = Some(attempt);
        assert!(matches!(
            fixture.store.write_event(&fixture.supervisor, request),
            Err(StateError::WorkEventInvalid(_))
        ));
    }

    let mut valid = event(
        "valid-rework",
        EventType::ReworkRequested,
        json!({
            "d1_failure_event_id":"d1-failed",
            "failed_candidate_sha256":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            "rework_round":1
        }),
    );
    valid.role_instance_id = "supervisor-a".into();
    fixture
        .store
        .write_event(&fixture.supervisor, valid)
        .unwrap();

    let mut duplicate_round = event(
        "duplicate-round",
        EventType::ReworkRequested,
        json!({
            "d1_failure_event_id":"d1-failed",
            "failed_candidate_sha256":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            "rework_round":1
        }),
    );
    duplicate_round.role_instance_id = "supervisor-a".into();
    assert!(matches!(
        fixture
            .store
            .write_event(&fixture.supervisor, duplicate_round),
        Err(StateError::WorkEventInvalid(_))
    ));
}

#[test]
fn slk_440_rework_request_requires_round_bound_investigation_mode() {
    let fixture = Fixture::new();
    fixture
        .store
        .handoff_token(&fixture.supervisor, handoff(2, "supervisor-a", "checker-a"))
        .unwrap();
    let mut failed = event(
        "d1-failed-440",
        EventType::D1Failed,
        json!({"candidate_sha256":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}),
    );
    failed.role_instance_id = "checker-a".into();
    fixture.store.write_event(&fixture.checker, failed).unwrap();
    let mut escalation = handoff(3, "checker-a", "supervisor-a");
    escalation.payload_type = "D1_FAILURE_ESCALATION".into();
    fixture
        .store
        .handoff_token(&fixture.checker, escalation)
        .unwrap();
    let connection = slk_state_core::schema::open_database(fixture._root.path()).unwrap();
    connection
        .execute(
            "UPDATE runs SET slk_version='4.4.0' WHERE run_id='run-a'",
            [],
        )
        .unwrap();

    for (event_id, details) in [
        (
            "missing-mode-440",
            json!({
                "d1_failure_event_id":"d1-failed-440",
                "failed_candidate_sha256":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                "rework_round":1
            }),
        ),
        (
            "wrong-mode-440",
            json!({
                "d1_failure_event_id":"d1-failed-440",
                "failed_candidate_sha256":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                "rework_round":1,
                "investigation_mode":"AGGRESSIVE"
            }),
        ),
    ] {
        let mut request = event(event_id, EventType::ReworkRequested, details);
        request.role_instance_id = "supervisor-a".into();
        assert!(matches!(
            fixture.store.write_event(&fixture.supervisor, request),
            Err(StateError::WorkEventInvalid(_))
        ));
    }

    let mut valid = event(
        "valid-mode-440",
        EventType::ReworkRequested,
        json!({
            "d1_failure_event_id":"d1-failed-440",
            "failed_candidate_sha256":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            "rework_round":1,
            "investigation_mode":"STANDARD"
        }),
    );
    valid.role_instance_id = "supervisor-a".into();
    fixture
        .store
        .write_event(&fixture.supervisor, valid)
        .unwrap();
}

#[test]
fn slk_442_second_d1_failure_records_supervisor_action_without_host_plan_judgment() {
    // Exercise both explicit Supervisor choices from independent, identical histories.
    for record_second_rework in [true, false] {
        let (fixture, first_candidate_sha256) = legacy_d1_candidate_chain(
            "candidate-message-a",
            Some("candidate-message-a"),
            "candidate-message-a",
        );
        let mut first_rework = event(
            "first-rework-442",
            EventType::ReworkRequested,
            json!({
                "d1_failure_event_id":"legacy-d1-failed",
                "failed_candidate_sha256":first_candidate_sha256,
                "rework_round":1
            }),
        );
        first_rework.role_instance_id = "supervisor-a".into();
        fixture
            .store
            .write_event(&fixture.supervisor, first_rework)
            .unwrap();

        let mut to_worker = handoff(6, "supervisor-a", "worker-a");
        to_worker.payload_type = "D1_REWORK_DIRECTIVE".into();
        fixture
            .store
            .handoff_token(&fixture.supervisor, to_worker)
            .unwrap();

        let second_candidate =
            json!({"kind":"commit","commit":"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"});
        let second_candidate_sha256 = format!(
            "{:x}",
            Sha256::digest(serde_json::to_vec(&second_candidate).unwrap())
        );
        let mut candidate_event = event(
            "second-candidate-submitted-442",
            EventType::CandidateSubmitted,
            json!({
                "candidate":second_candidate,
                "source_message_id":"second-source-message-442",
                "handoff_message_id":"second-candidate-message-442"
            }),
        );
        candidate_event.attempt = Some(2);
        fixture
            .store
            .write_event(&fixture.worker, candidate_event)
            .unwrap();
        let mut started = event(
            "second-transport-started-442",
            EventType::TransportStarted,
            json!({"message_id":"second-candidate-message-442"}),
        );
        started.attempt = Some(2);
        fixture.store.write_event(&fixture.worker, started).unwrap();
        let mut to_checker = handoff(7, "worker-a", "checker-a");
        to_checker.payload_type = "CANDIDATE_READY".into();
        fixture
            .store
            .handoff_token(&fixture.worker, to_checker)
            .unwrap();
        let mut second_failed = event(
            "second-d1-failed-442",
            EventType::D1Failed,
            json!({"verdict":"FAIL","candidate_message_id":"second-candidate-message-442"}),
        );
        second_failed.role_instance_id = "checker-a".into();
        second_failed.attempt = Some(2);
        fixture
            .store
            .write_event(&fixture.checker, second_failed)
            .unwrap();
        let mut escalation = handoff(8, "checker-a", "supervisor-a");
        escalation.payload_type = "D1_FAILURE_ESCALATION".into();
        fixture
            .store
            .handoff_token(&fixture.checker, escalation)
            .unwrap();

        let connection = slk_state_core::schema::open_database(fixture._root.path()).unwrap();
        connection
            .execute(
                "UPDATE runs SET slk_version='4.4.2' WHERE run_id='run-a'",
                [],
            )
            .unwrap();

        let mut second_rework = event(
            "second-rework-442",
            EventType::ReworkRequested,
            json!({
                "d1_failure_event_id":"second-d1-failed-442",
                "failed_candidate_sha256":second_candidate_sha256,
                "rework_round":2,
                "investigation_mode":"BOUNDED_OWNER_APPROVED_INVESTIGATION"
            }),
        );
        second_rework.role_instance_id = "supervisor-a".into();
        second_rework.attempt = Some(2);
        if record_second_rework {
            fixture
        .store
        .write_event(&fixture.supervisor, second_rework)
        .expect("Supervisor owns the investigation and plan decision; host preserves the exact failure and round");
            continue;
        }

        connection
        .execute(
            "INSERT INTO cell_nodes
             (run_id,go_id,cell_id,ordinal,title,objective,state)
             VALUES ('run-a','GO-001','CELL-002',2,'Existing next CELL','Existing objective','planned')",
            [],
        )
        .unwrap();
        let token_before = fixture.store.current_token("run-a").unwrap();
        assert!(matches!(
        fixture.store.revise_plan(
            &fixture.supervisor,
            RevisePlanRequest {
                event_id: "invalid-single-successor-442".into(),
                run_id: "run-a".into(),
                snapshot: json!({
                    "expected_plan_revision": 1,
                    "cell_split": {
                        "source_go_id": "GO-001",
                        "source_cell_id": "CELL-001",
                        "failure_event_ids": ["legacy-d1-failed", "second-d1-failed-442"],
                        "successor_cells": [
                            {"cell_id":"CELL-001-ONLY","title":"Still oversized","objective":"One replacement is not a split"}
                        ]
                    }
                }),
                reason: "invalid one-way replacement".into(),
                occurred_at: "2026-09-20T00:00:04Z".into(),
            },
        ),
        Err(StateError::InvalidPlan(_))
    ));
        let revision = fixture
        .store
        .revise_plan(
            &fixture.supervisor,
            RevisePlanRequest {
                event_id: "split-after-second-failure-442".into(),
                run_id: "run-a".into(),
                snapshot: json!({
                    "expected_plan_revision": 1,
                    "cell_split": {
                        "source_go_id": "GO-001",
                        "source_cell_id": "CELL-001",
                        "failure_event_ids": ["legacy-d1-failed", "second-d1-failed-442"],
                        "successor_cells": [
                            {"cell_id":"CELL-001-A","title":"Bounded fix A","objective":"First bounded correction"},
                            {"cell_id":"CELL-001-B","title":"Bounded fix B","objective":"Second bounded correction"}
                        ]
                    }
                }),
                reason: "second consecutive formal D1 failure requires smaller successor CELLs".into(),
                occurred_at: "2026-09-20T00:00:04Z".into(),
            },
        )
        .unwrap();

        assert_eq!(revision, 2);
        assert_eq!(fixture.store.current_token("run-a").unwrap(), token_before);
        let projection = fixture.store.query_run("run-a").unwrap();
        let cells = &projection.go_nodes[0].cell_nodes;
        assert_eq!(
            cells
                .iter()
                .map(|cell| (cell.cell_id.as_str(), cell.ordinal, cell.state.as_str()))
                .collect::<Vec<_>>(),
            vec![
                ("CELL-001", 1, "split"),
                ("CELL-001-A", 2, "planned"),
                ("CELL-001-B", 3, "planned"),
                ("CELL-002", 4, "planned"),
            ]
        );
        assert!(projection
            .events
            .iter()
            .any(|event| event.event_type == "CELL_SPLIT"));

        assert!(matches!(
            fixture.store.revise_plan(
                &fixture.supervisor,
                RevisePlanRequest {
                    event_id: "stale-split-442".into(),
                    run_id: "run-a".into(),
                    snapshot: json!({
                        "expected_plan_revision": 1,
                        "cell_split": {
                            "source_go_id": "GO-001",
                            "source_cell_id": "CELL-001",
                            "failure_event_ids": ["legacy-d1-failed", "second-d1-failed-442"],
                            "successor_cells": [
                                {"cell_id":"CELL-001-C","title":"C","objective":"C"},
                                {"cell_id":"CELL-001-D","title":"D","objective":"D"}
                            ]
                        }
                    }),
                    reason: "stale replay".into(),
                    occurred_at: "2026-09-20T00:00:05Z".into(),
                },
            ),
            Err(StateError::PlanRevisionMismatch {
                requested: 1,
                current: 2
            })
        ));

        fixture
            .store
            .commit_delivery_start(
                &fixture.supervisor,
                fixture.revisioned_start_request(
                    9,
                    "supervisor-a",
                    "checker-a",
                    "CELL-001",
                    "PLAN_REVISED",
                    "ocrv-checker",
                ),
            )
            .unwrap();
        fixture
            .store
            .commit_delivery_start(
                &fixture.checker,
                fixture.revisioned_start_request(
                    10,
                    "checker-a",
                    "worker-a",
                    "CELL-001-A",
                    "WORKER_TASK",
                    "dsh-worker",
                ),
            )
            .unwrap();
        assert_eq!(
            fixture
                .store
                .current_token("run-a")
                .unwrap()
                .owner_role_instance_id,
            "worker-a"
        );
    }
}

#[test]
fn rework_request_resolves_the_legacy_d1_candidate_through_one_started_handoff() {
    let (fixture, candidate_sha256) = legacy_d1_candidate_chain(
        "candidate-message-a",
        Some("candidate-message-a"),
        "candidate-message-a",
    );
    let mut request = event(
        "legacy-rework",
        EventType::ReworkRequested,
        json!({
            "d1_failure_event_id":"legacy-d1-failed",
            "failed_candidate_sha256":candidate_sha256,
            "rework_round":1
        }),
    );
    request.role_instance_id = "supervisor-a".into();

    fixture
        .store
        .write_event(&fixture.supervisor, request)
        .unwrap();
}

#[test]
fn legacy_d1_candidate_resolution_rejects_missing_wrong_or_changed_handoff_evidence() {
    for (candidate_message, start_message, failure_message, changed_hash) in [
        ("candidate-message-a", None, "candidate-message-a", false),
        (
            "candidate-message-a",
            Some("candidate-message-other"),
            "candidate-message-a",
            false,
        ),
        (
            "candidate-message-other",
            Some("candidate-message-a"),
            "candidate-message-a",
            false,
        ),
        (
            "candidate-message-a",
            Some("candidate-message-a"),
            "candidate-message-a",
            true,
        ),
    ] {
        let (fixture, candidate_sha256) =
            legacy_d1_candidate_chain(candidate_message, start_message, failure_message);
        let mut request = event(
            "legacy-rework-rejected",
            EventType::ReworkRequested,
            json!({
                "d1_failure_event_id":"legacy-d1-failed",
                "failed_candidate_sha256": if changed_hash { "b".repeat(64) } else { candidate_sha256 },
                "rework_round":1
            }),
        );
        request.role_instance_id = "supervisor-a".into();
        assert!(matches!(
            fixture.store.write_event(&fixture.supervisor, request),
            Err(StateError::WorkEventInvalid(_))
        ));
    }
}

#[test]
fn legacy_d1_candidate_resolution_rejects_duplicate_or_wrong_attempt_candidate_events() {
    for (candidate_attempt, duplicate_candidate) in [(2, false), (1, true)] {
        let (fixture, candidate_sha256) = legacy_d1_candidate_chain_with_shape(
            "candidate-message-a",
            Some("candidate-message-a"),
            "candidate-message-a",
            candidate_attempt,
            1,
            duplicate_candidate,
        );
        let mut request = event(
            "legacy-rework-shape-rejected",
            EventType::ReworkRequested,
            json!({
                "d1_failure_event_id":"legacy-d1-failed",
                "failed_candidate_sha256":candidate_sha256,
                "rework_round":1
            }),
        );
        request.role_instance_id = "supervisor-a".into();
        assert!(matches!(
            fixture.store.write_event(&fixture.supervisor, request),
            Err(StateError::WorkEventInvalid(_))
        ));
    }
}

fn legacy_d1_candidate_chain(
    candidate_message: &str,
    start_message: Option<&str>,
    failure_message: &str,
) -> (Fixture, String) {
    legacy_d1_candidate_chain_with_shape(
        candidate_message,
        start_message,
        failure_message,
        1,
        1,
        false,
    )
}

fn legacy_d1_candidate_chain_with_shape(
    candidate_message: &str,
    start_message: Option<&str>,
    failure_message: &str,
    candidate_attempt: u32,
    start_attempt: u32,
    duplicate_candidate: bool,
) -> (Fixture, String) {
    let fixture = Fixture::worker_active();
    let candidate = json!({"kind":"commit","commit":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"});
    let candidate_sha256 = format!(
        "{:x}",
        Sha256::digest(serde_json::to_vec(&candidate).unwrap())
    );
    let mut candidate_event = event(
        "legacy-candidate-submitted",
        EventType::CandidateSubmitted,
        json!({
            "candidate":candidate,
            "source_message_id":"source-message-a",
            "handoff_message_id":candidate_message
        }),
    );
    candidate_event.attempt = Some(candidate_attempt);
    fixture
        .store
        .write_event(&fixture.worker, candidate_event)
        .unwrap();
    if duplicate_candidate {
        let mut duplicate = event(
            "legacy-candidate-submitted-duplicate",
            EventType::CandidateSubmitted,
            json!({
                "candidate":candidate,
                "source_message_id":"source-message-a",
                "handoff_message_id":candidate_message
            }),
        );
        duplicate.attempt = Some(candidate_attempt);
        fixture
            .store
            .write_event(&fixture.worker, duplicate)
            .unwrap();
    }
    if let Some(message_id) = start_message {
        let mut started = event(
            "legacy-transport-started",
            EventType::TransportStarted,
            json!({"message_id":message_id}),
        );
        started.attempt = Some(start_attempt);
        fixture.store.write_event(&fixture.worker, started).unwrap();
    }
    let mut to_checker = handoff(4, "worker-a", "checker-a");
    to_checker.payload_type = "CANDIDATE_READY".into();
    fixture
        .store
        .handoff_token(&fixture.worker, to_checker)
        .unwrap();
    let mut failed = event(
        "legacy-d1-failed",
        EventType::D1Failed,
        json!({"verdict":"FAIL","candidate_message_id":failure_message}),
    );
    failed.role_instance_id = "checker-a".into();
    fixture.store.write_event(&fixture.checker, failed).unwrap();
    let mut escalation = handoff(5, "checker-a", "supervisor-a");
    escalation.payload_type = "D1_FAILURE_ESCALATION".into();
    fixture
        .store
        .handoff_token(&fixture.checker, escalation)
        .unwrap();
    (fixture, candidate_sha256)
}

#[test]
fn unbound_onsite_owner_labels_do_not_close_an_active_ow() {
    let fixture = Fixture::new();
    fixture.store.handoff_token(&fixture.supervisor, handoff(2, "supervisor-a", "checker-a")).unwrap();
    let mut pass = event("accepted-before-close", EventType::D1Passed, json!({"verdict":"PASS"}));
    pass.role_instance_id = "checker-a".into();
    fixture.store.write_event(&fixture.checker, pass).unwrap();
    let mut ready=handoff(3, "checker-a", "supervisor-a"); ready.payload_type="D2_READY".into();
    fixture.store.handoff_token(&fixture.checker, ready).unwrap();
    let db = slk_state_core::schema::open_database(fixture._root.path()).unwrap();
    db.execute("UPDATE runs SET slk_version='4.4.2' WHERE run_id='run-a'", []).unwrap();
    fixture.store.bind_overwatcher(&fixture.supervisor, BindOverwatcherRequest {
        event_id:"bind-incomplete-close-ow".into(), run_id:"run-a".into(),
        identity:role("overwatcher-a", Role::Overwatcher), endpoint:endpoint("session-overwatcher-a"),
        observation_mode:ObservationMode::ForegroundActiveTurn, cadence_seconds:600,
        foreground_turn_id:"old-ow-turn".into(), native_active_session_evidence_ref:"original-proof".into(),
        binding_revision:1, canonical_task_id:"original-ow".into(), reason:"observe".into(),
        occurred_at:"2026-09-20T00:02:00Z".into()
    }).unwrap();
    let mut d2 = event("accepted-d2", EventType::D2Passed, json!({"verdict":"PASS"}));
    d2.role_instance_id="supervisor-a".into(); d2.go_id=None; d2.cell_id=None; d2.attempt=None;
    fixture.store.write_event(&fixture.supervisor, d2).unwrap();
    let terminal = fixture.store.query_run("run-a").unwrap();
    let snapshot = fixture._root.path().join("owner-close-terminal.json");
    fs::write(&snapshot, serde_json::to_vec(&terminal).unwrap()).unwrap();
    db.execute("UPDATE runs SET slk_version='4.4.3' WHERE run_id='run-a'", []).unwrap();
    let proof = fixture._root.path().join("owner-close-census.json");
    fs::write(&proof, serde_json::to_vec(&json!({
        "schema_version":"slk.run-quiescence/v1","run_id":"run-a","pause_id":"owner-close",
        "runtime_revision":terminal.runtime_snapshot.as_ref().unwrap().runtime_revision,
        "status":"NOT_QUIESCENT","attempt_roots":[fixture._root.path()],
        "observed_at":"2026-09-20T00:03:00Z","inspections":[]
    })).unwrap()).unwrap();
    let owner = fixture._root.path().join("owner-close-authorization.json");
    fs::write(&owner, br#"{"run_id":"run-a","approved":true,"request":"Complete this accepted Run without rewriting history"}"#).unwrap();
    let stop = fixture._root.path().join("owner-close-ow-stop.json");
    let stopped = json!({"run_id":"run-a","role_instance_id":"overwatcher-a",
        "session_id":"session-overwatcher-a","status":"COMPLETED","source":"collaboration.list_agents"});
    fs::write(&stop, serde_json::to_vec(&stopped).unwrap()).unwrap();
    let hash = |path: &std::path::Path| format!("{:x}",Sha256::digest(fs::read(path).unwrap()));
    let mut close = event("owner-authorized-run-close", EventType::RunClosed, json!({
        "terminal_snapshot_path":snapshot,"terminal_snapshot_sha256":hash(&snapshot),
        "quiescence_path":proof,"quiescence_sha256":hash(&proof),
        "close_binding_path":snapshot,"close_binding_sha256":hash(&snapshot)
    }));
    close.role_instance_id="supervisor-a".into(); close.go_id=None; close.cell_id=None; close.attempt=None;
    close.occurred_at="2026-09-20T00:03:00Z".into();
    assert!(fixture.store.write_event(&fixture.supervisor,close.clone()).is_err());
    close.details["incomplete_ow_close"] = json!({
        "role_instance_id":"overwatcher-a","binding_revision":1,
        "owner_authorization_path":owner,"owner_authorization_sha256":hash(&owner),
        "stop_evidence_path":stop,"stop_evidence_sha256":hash(&stop),
        "reason":"Owner directs terminal close; old OW final cycle is missing, not fabricated"
    });
    let writers = fixture._root.path().join("actual-stopped-writers.json");
    fs::write(&writers, serde_json::to_vec(&json!({"run_id":"run-a",
        "status":"NO_ACTIVE_ENGINEERING_WRITERS", "observed_at":close.occurred_at,
        "dsh":{"status":"NATIVE_SESSION_STOPPED","session_id":"session-worker-a","active_matching_hosts":[]},
        "ocrv":{"checked_executor_identities":1,"active_matching_executors":[]},
        "supervisor":{"session_id":"session-supervisor-a","current_coordinator_only":true},
        "history_gaps_preserved":true})).unwrap()).unwrap();
    close.details["incomplete_ow_close"]["writer_stop_evidence_path"]=json!(writers);
    close.details["incomplete_ow_close"]["writer_stop_evidence_sha256"]=json!(hash(&writers));
    let good_writers: serde_json::Value=serde_json::from_slice(&fs::read(&writers).unwrap()).unwrap();
    for damage in ["active-ocrv", "active-dsh", "wrong-session", "not-coordinator"] {
        let mut bad=good_writers.clone();
        match damage {
            "active-ocrv" => bad["ocrv"]["active_matching_executors"]=json!([{"pid":123}]),
            "active-dsh" => bad["dsh"]["active_matching_hosts"]=json!([{"pid":123}]),
            "wrong-session" => bad["dsh"]["session_id"]=json!("another-worker"),
            _ => bad["supervisor"]["current_coordinator_only"]=json!(false),
        }
        fs::write(&writers,serde_json::to_vec(&bad).unwrap()).unwrap();
        close.details["incomplete_ow_close"]["writer_stop_evidence_sha256"]=json!(hash(&writers));
        assert!(fixture.store.write_event(&fixture.supervisor,close.clone()).is_err(),"{damage}");
    }
    fs::write(&writers,serde_json::to_vec(&good_writers).unwrap()).unwrap();
    close.details["incomplete_ow_close"]["writer_stop_evidence_sha256"]=json!(hash(&writers));
    let mut unknown=stopped.clone(); unknown["status"]=json!("UNKNOWN");
    fs::write(&stop, serde_json::to_vec(&unknown).unwrap()).unwrap();
    close.details["incomplete_ow_close"]["stop_evidence_sha256"]=json!(hash(&stop));
    assert!(fixture.store.write_event(&fixture.supervisor,close.clone()).is_err());
    fs::write(&stop, serde_json::to_vec(&stopped).unwrap()).unwrap();
    close.details["incomplete_ow_close"]["stop_evidence_sha256"]=json!(hash(&stop));
    assert!(fixture.store.write_event(&fixture.supervisor,close).is_err());
    let result=fixture.store.query_run("run-a").unwrap();
    assert_eq!(result.summary.closure_state,"open");
    assert_eq!(result.overwatch_cycles.len(),0);
    let gap: i64=db.query_row("SELECT COUNT(*) FROM overwatcher_binding_transitions WHERE run_id='run-a' AND transition_type='INCOMPLETE_SHUTDOWN'",[],|row|row.get(0)).unwrap();
    assert_eq!(gap,0);
}

fn save_close_json(path: &std::path::Path, value: &serde_json::Value) -> String {
    fs::write(path, serde_json::to_vec(value).unwrap()).unwrap();
    format!("{:x}", Sha256::digest(fs::read(path).unwrap()))
}

fn current_test_process() -> serde_json::Value {
    #[cfg(windows)]
    let creation = {
        use std::ffi::c_void;
        #[link(name = "kernel32")]
        extern "system" {
            fn GetCurrentProcess() -> *mut c_void;
            fn GetProcessTimes(handle: *mut c_void, creation: *mut u64, exit: *mut u64, kernel: *mut u64, user: *mut u64) -> i32;
        }
        let (mut created, mut exit, mut kernel, mut user) = (0, 0, 0, 0);
        assert_ne!(unsafe { GetProcessTimes(GetCurrentProcess(), &mut created, &mut exit, &mut kernel, &mut user) }, 0);
        format!("win-filetime:{created}")
    };
    #[cfg(not(windows))]
    let creation = {
        let stat = fs::read_to_string(format!("/proc/{}/stat", std::process::id())).unwrap();
        format!("proc-start:{}", stat.rsplit_once(')').unwrap().1.split_whitespace().nth(19).unwrap())
    };
    json!({"pid":std::process::id(),"creation_time":creation})
}

fn ready_close_fixture() -> (Fixture, WriteRequest) {
    let fixture = Fixture::new();
    fixture.store.handoff_token(&fixture.supervisor, handoff(2, "supervisor-a", "checker-a")).unwrap();
    let mut pass = event("d1-close-ready", EventType::D1Passed, json!({"verdict":"PASS"}));
    pass.role_instance_id = "checker-a".into();
    fixture.store.write_event(&fixture.checker, pass).unwrap();
    let mut ready = handoff(3, "checker-a", "supervisor-a"); ready.payload_type = "D2_READY".into();
    fixture.store.handoff_token(&fixture.checker, ready).unwrap();
    let db = slk_state_core::schema::open_database(fixture._root.path()).unwrap();
    db.execute("UPDATE runs SET slk_version='4.3.5' WHERE run_id='run-a'", []).unwrap();
    let mut d2 = event("d2-close-ready", EventType::D2Passed, json!({"verdict":"PASS"}));
    d2.role_instance_id = "supervisor-a".into(); d2.go_id = None; d2.cell_id = None; d2.attempt = None;
    fixture.store.write_event(&fixture.supervisor, d2).unwrap();
    let snapshot = fixture._root.path().join("close-terminal.json");
    let hash = save_close_json(&snapshot, &serde_json::to_value(fixture.store.query_run("run-a").unwrap()).unwrap());
    db.execute("UPDATE runs SET slk_version='4.4.3' WHERE run_id='run-a'", []).unwrap();
    let mut close = event("standard-close", EventType::RunClosed, json!({
        "terminal_snapshot_path":snapshot,"terminal_snapshot_sha256":hash,
        "close_binding_path":snapshot,"close_binding_sha256":hash}));
    close.role_instance_id = "supervisor-a".into(); close.go_id = None; close.cell_id = None; close.attempt = None;
    close.occurred_at = "2026-09-20T00:05:00Z".into();
    (fixture, close)
}

fn stopped_historical_resume(fixture: &Fixture) -> (std::path::PathBuf, serde_json::Value) {
    let root = fixture._root.path();
    let source = root.join("run-a/message-old");
    let resumed = source.join("native-resumes/11111111-1111-4111-8111-111111111111");
    fs::create_dir_all(&resumed).unwrap();
    let home = root.join("runtime/runs/worker-instance/home");
    let session = home.join("sessions/project/session-worker-a/session.v4.jsonl.zstd");
    fs::create_dir_all(session.parent().unwrap()).unwrap();
    fs::write(&session, b"isolated closed native Session bytes").unwrap();
    let endpoint = json!({"schema_version":"slk.transport-endpoint/v1","run_id":"run-a","role":"worker",
        "role_instance_id":"worker-a","endpoint_version":1,"adapter":"dsh-worker","host_id":"local","state":"active",
        "address":{"session_id":"session-worker-a","runtime_root":root.join("runtime"),"instance_id":"worker-instance","cwd":root}});
    let envelope = json!({"schema_version":"slk.transport-envelope/v1","run_id":"run-a","cell_id":"CELL-001",
        "message_id":"message-old","receiver_role_instance_id":"worker-a","receiver_role":"worker","receiver_endpoint_version":1,
        "payload_sha256":"a".repeat(64)});
    let start = json!({"schema_version":"slk.native-start/v2","status":"STARTED","adapter":"dsh-worker","run_id":"run-a","cell_id":"CELL-001",
        "message_id":"message-old","request_sha256":"a".repeat(64),"native_request_sha256":"b".repeat(64),
        "observed_at":"2026-09-20T00:00:00Z","process":{"pid":4294967295_u32,"creation_time":"win-filetime:1"},
        "native_task":{"kind":"dsh-session","id":"session-worker-a","status":"RUNNING"}});
    let mut original_hashes = serde_json::Map::new();
    for (name, value) in [("endpoint.json", &endpoint), ("envelope.json", &envelope), ("started.json", &start)] {
        original_hashes.insert(name.into(), json!(save_close_json(&source.join(name), value)));
        save_close_json(&resumed.join(name), value);
    }
    fs::write(resumed.join("instructions.md"), b"Original continuation instructions").unwrap();
    let marker = json!({"schema_version":"slk.worker-native-resume/v1","invocation_id":resumed.file_name().unwrap().to_str().unwrap(),
        "original_source":source,"original_source_sha256":format!("{:x}",Sha256::digest(serde_json::to_vec(&original_hashes).unwrap())),
        "binding_sha256":"c".repeat(64),"instructions_sha256":format!("{:x}",Sha256::digest(fs::read(resumed.join("instructions.md")).unwrap())),
        "coordinator_process":{"pid":4294967294_u32,"creation_time":"win-filetime:1"}});
    let marker_hash = save_close_json(&resumed.join("native-resume.json"), &marker);
    let start_hash = format!("{:x}",Sha256::digest(fs::read(resumed.join("started.json")).unwrap()));
    let host = json!({"id":"d".repeat(64),"pid":4294967293_u32,"process_created":"win-filetime:1","native_home":home,
        "observed_at":"2026-09-20T00:03:00Z","coverage":"COMPLETE","omitted":0,"liveness":"EXITED",
        "objects":[{"session_id":"session-worker-a","source":session,"event_source":"DSH_NATIVE_EMISSION","status":"RUNNING"}]});
    let row = json!({"native_start_path":resumed.join("started.json"),"native_start_sha256":start_hash,
        "message_id":"message-old","status":"UNKNOWN","processes":[],
        "reason":"native continuation lacks its exact frozen historical Host reference",
        "current_safety":{"status":"STOPPED","source_gap":"FROZEN_HOST_UNAVAILABLE","native_start_sha256":start_hash,
            "endpoint_sha256":format!("{:x}",Sha256::digest(fs::read(resumed.join("endpoint.json")).unwrap())),
            "resume_marker_sha256":marker_hash,"coordinator":{"pid":4294967294_u32,"creation_time":"win-filetime:1","exists":false,"identity_matches":false},
            "observed_at":"2026-09-20T00:03:00Z","native_stop":{
                "session":{"status":"NATIVE_SESSION_STOPPED","session_id":"session-worker-a","path":session,
                    "sha256":format!("{:x}",Sha256::digest(fs::read(&session).unwrap())),"last_seq":5,"turn":1,"turn_end_seq":5,"turn_ended_at":"2026-09-20T00:02:00Z"},
                "launcher":{"pid":4294967295_u32,"creation_time":"win-filetime:1","exists":false,"identity_matches":false},
                "native_probe":{"coverage":"UNKNOWN","hosts":[host]}}}});
    (resumed, row)
}

#[test]
fn standard_close_preserves_historical_unknown_only_with_exact_current_stop() {
    for damage in [None, Some("missing-proof"), Some("active"), Some("unknown-current"), Some("wrong-session"),
        Some("start-hash"), Some("endpoint-hash"), Some("marker-hash"), Some("instructions"), Some("source-hash"),
        Some("native-host"), Some("durable-hash"), Some("noncreator"), Some("coordinator"), Some("wrong-ancestry"),
        Some("live-coordinator"), Some("live-native-host")] {
        let (fixture, mut close) = ready_close_fixture();
        let (resumed, mut row) = stopped_historical_resume(&fixture);
        match damage {
            Some("missing-proof") => { row.as_object_mut().unwrap().remove("current_safety"); }
            Some("active") => row["current_safety"]["native_stop"]["launcher"]["exists"] = json!(true),
            Some("unknown-current") => row["current_safety"]["native_stop"]["launcher"]["exists"] = json!(null),
            Some("wrong-session") => row["current_safety"]["native_stop"]["session"]["session_id"] = json!("foreign"),
            Some("start-hash") => row["native_start_sha256"] = json!("0".repeat(64)),
            Some("endpoint-hash") => row["current_safety"]["endpoint_sha256"] = json!("0".repeat(64)),
            Some("marker-hash") => row["current_safety"]["resume_marker_sha256"] = json!("0".repeat(64)),
            Some("instructions") => fs::write(resumed.join("instructions.md"), b"changed").unwrap(),
            Some("source-hash") | Some("wrong-ancestry") => {
                let path = resumed.join("native-resume.json");
                let mut marker: serde_json::Value = serde_json::from_slice(&fs::read(&path).unwrap()).unwrap();
                if damage == Some("source-hash") { marker["original_source_sha256"] = json!("0".repeat(64)); }
                else { marker["original_source"] = json!(fixture._root.path()); }
                row["current_safety"]["resume_marker_sha256"] = json!(save_close_json(&path, &marker));
            }
            Some("native-host") => row["current_safety"]["native_stop"]["native_probe"]["hosts"][0]["liveness"] = json!("UNKNOWN"),
            Some("durable-hash") => row["current_safety"]["native_stop"]["session"]["sha256"] = json!("0".repeat(64)),
            Some("coordinator") => row["current_safety"]["coordinator"]["pid"] = json!(42),
            Some("live-coordinator") => {
                let path = resumed.join("native-resume.json");
                let mut marker: serde_json::Value = serde_json::from_slice(&fs::read(&path).unwrap()).unwrap();
                marker["coordinator_process"] = current_test_process();
                row["current_safety"]["coordinator"] = marker["coordinator_process"].clone();
                row["current_safety"]["coordinator"]["exists"] = json!(false);
                row["current_safety"]["coordinator"]["identity_matches"] = json!(false);
                row["current_safety"]["resume_marker_sha256"] = json!(save_close_json(&path, &marker));
            }
            Some("live-native-host") => {
                let live = current_test_process();
                row["current_safety"]["native_stop"]["native_probe"]["hosts"][0]["pid"] = live["pid"].clone();
                row["current_safety"]["native_stop"]["native_probe"]["hosts"][0]["process_created"] = live["creation_time"].clone();
            }
            Some("noncreator") => {
                close.role_instance_id = "different-creator".into();
            }
            _ => {}
        }
        if damage == Some("active") { row["current_safety"]["native_stop"]["launcher"]["identity_matches"] = json!(true); }
        let census = json!({"schema_version":"slk.run-quiescence/v1","run_id":"run-a","pause_id":"close",
            "runtime_revision":fixture.store.query_run("run-a").unwrap().runtime_snapshot.unwrap().runtime_revision,
            "status":"NOT_QUIESCENT","attempt_roots":[fixture._root.path()],"observed_at":"2026-09-20T00:05:00Z","inspections":[row]});
        let path = fixture._root.path().join("close-census.json");
        close.details["quiescence_sha256"] = json!(save_close_json(&path, &census)); close.details["quiescence_path"] = json!(path);
        let result = fixture.store.write_event(&fixture.supervisor, close);
        assert_eq!(result.is_ok(), damage.is_none(), "{damage:?}: {result:?}");
        let preserved: serde_json::Value = serde_json::from_slice(&fs::read(path).unwrap()).unwrap();
        assert_eq!(preserved["inspections"][0]["status"], "UNKNOWN");
    }
}

#[test]
fn accepted_desktop_close_requires_exact_not_sent_boundary() {
    for damage in [None, Some("no-boundary"), Some("sent"), Some("uncertain"), Some("wrong-message"), Some("wrong-endpoint"), Some("wrong-hash"), Some("stale-census")] {
        let (fixture, mut close) = ready_close_fixture();
        let source = fixture._root.path().join("run-a/message-unsent");
        fs::create_dir_all(&source).unwrap();
        let endpoint = json!({"run_id":"run-a","adapter":"codex-app-server","role":"supervisor","address":{"desktop":{}}});
        let endpoint_hash = save_close_json(&source.join("endpoint.json"), &endpoint);
        save_close_json(&source.join("envelope.json"), &json!({"run_id":"run-a","message_id":"message-unsent","payload_sha256":"a".repeat(64)}));
        save_close_json(&source.join("accepted.json"), &json!({"status":"accepted"}));
        let mut boundary = json!({"schema_version":"slk.desktop-send-boundary/v1","phase":"NOT_SENT","run_id":"run-a",
            "message_id":"message-unsent","request_sha256":"a".repeat(64),"endpoint_sha256":endpoint_hash,
            "error_code":"CODEX_THREAD_STATE_UNKNOWN","observed_at":"2026-09-20T00:03:00Z"});
        match damage {
            Some("sent") => { save_close_json(&source.join("desktop-send.json"), &json!({})); }
            Some("uncertain") => { save_close_json(&source.join("desktop-readback-anchor.json"), &json!({})); }
            Some("wrong-message") => boundary["message_id"] = json!("different-message"),
            Some("wrong-endpoint") => boundary["endpoint_sha256"] = json!("0".repeat(64)),
            Some("wrong-hash") => boundary["request_sha256"] = json!("0".repeat(64)),
            _ => {}
        }
        if damage != Some("no-boundary") { save_close_json(&source.join("desktop-pre-send-failure.json"), &boundary); }
        let census = json!({"schema_version":"slk.run-quiescence/v1","run_id":"run-a","pause_id":"close",
            "runtime_revision":fixture.store.query_run("run-a").unwrap().runtime_snapshot.unwrap().runtime_revision,
            "status":"QUIESCENT","attempt_roots":[fixture._root.path()],
            "observed_at":if damage == Some("stale-census") {"2026-09-20T00:03:00Z"} else {"2026-09-20T00:05:00Z"},
            "inspections":[{"native_start_path":source.join("started.json"),"native_start_sha256":null,
                "message_id":"message-unsent","status":"STAGED_NOT_STARTED","processes":[]}]});
        let path = fixture._root.path().join("close-census.json");
        close.details["quiescence_sha256"] = json!(save_close_json(&path, &census)); close.details["quiescence_path"] = json!(path);
        let result = fixture.store.write_event(&fixture.supervisor, close);
        assert_eq!(result.is_ok(), damage.is_none(), "{damage:?}: {result:?}");
    }
}

#[test]
fn historical_current_stop_allows_already_closed_ow_but_not_pause() {
    for pause in [false, true] {
        let (fixture, mut close) = ready_close_fixture();
        let db = slk_state_core::schema::open_database(fixture._root.path()).unwrap();
        db.execute("UPDATE runs SET slk_version='4.4.2' WHERE run_id='run-a'", []).unwrap();
        fixture.store.bind_overwatcher(&fixture.supervisor, BindOverwatcherRequest {
            event_id:"bind-stopped-ow".into(), run_id:"run-a".into(), identity:role("overwatcher-a",Role::Overwatcher),
            endpoint:endpoint("session-overwatcher-a"), observation_mode:ObservationMode::ForegroundActiveTurn,
            cadence_seconds:600, foreground_turn_id:"old-ow-turn".into(), native_active_session_evidence_ref:"native:old-ow".into(),
            binding_revision:1, canonical_task_id:"old-ow-task".into(), reason:"isolated closure fixture".into(),
            occurred_at:"2026-09-20T00:02:00Z".into(),
        }).unwrap();
        // Authenticated native close is independently exercised in overwatcher.rs.
        db.execute("UPDATE overwatcher_bindings SET lifecycle_state='archived',credential_state='revoked' WHERE run_id='run-a'", []).unwrap();
        db.execute("UPDATE runs SET slk_version='4.4.3' WHERE run_id='run-a'", []).unwrap();
        let (_, row) = stopped_historical_resume(&fixture);
        if pause {
            fixture.store.write_event(&fixture.supervisor,
                lifecycle_event(&fixture,"pause-current-stop","RUN_PAUSE_REQUESTED","pause-current-stop")).unwrap();
        }
        let census = json!({"schema_version":"slk.run-quiescence/v1","run_id":"run-a","pause_id":"pause-current-stop",
            "runtime_revision":fixture.store.query_run("run-a").unwrap().runtime_snapshot.unwrap().runtime_revision,
            "status":if pause {"QUIESCENT"} else {"NOT_QUIESCENT"},"attempt_roots":[fixture._root.path()],
            "observed_at":"2026-09-20T00:05:00Z","inspections":[row]});
        let path = fixture._root.path().join("closed-ow-census.json");
        let hash = save_close_json(&path,&census);
        if pause {
            close = lifecycle_event(&fixture,"pause-current-stop-confirm","RUN_PAUSED","pause-current-stop");
            close.occurred_at = "2026-09-20T00:05:00Z".into();
        }
        close.details["quiescence_path"] = json!(path); close.details["quiescence_sha256"] = json!(hash);
        let result = fixture.store.write_event(&fixture.supervisor,close);
        assert_eq!(result.is_ok(), !pause, "pause={pause}: {result:?}");
    }
}

struct Fixture {
    _root: tempfile::TempDir,
    store: StateStore,
    supervisor: slk_state_core::auth::Credential,
    checker: slk_state_core::auth::Credential,
    worker: slk_state_core::auth::Credential,
}

impl Fixture {
    fn new() -> Self {
        Self::from_request(init_request("run-a"))
    }

    fn two_cells() -> Self {
        let mut request = init_request("run-a");
        request.cell_nodes.push(CellDefinition {
            go_id: "GO-001".into(),
            cell_id: "CELL-002".into(),
            ordinal: 2,
            title: "CELL 2".into(),
            objective: "Implement the next bounded change".into(),
        });
        Self::from_request(request)
    }

    fn from_request(request: InitRunRequest) -> Self {
        let root = tempfile::tempdir().unwrap();
        let store = StateStore::new(root.path());
        let initialized = store.init_run(request).unwrap();
        let connection = slk_state_core::schema::open_database(root.path()).unwrap();
        connection
            .execute(
                "UPDATE runs SET slk_version='4.2.0' WHERE run_id='run-a'",
                [],
            )
            .unwrap();
        let checker = store
            .register_role(
                &initialized.supervisor_credential,
                role_request("register-checker", "checker-a", Role::Checker),
            )
            .unwrap();
        let worker = store
            .register_role(
                &checker.credential,
                role_request("register-worker", "worker-a", Role::Worker),
            )
            .unwrap();
        Self {
            _root: root,
            store,
            supervisor: initialized.supervisor_credential,
            checker: checker.credential,
            worker: worker.credential,
        }
    }

    fn worker_active() -> Self {
        let fixture = Self::new();
        fixture
            .store
            .handoff_token(&fixture.supervisor, handoff(2, "supervisor-a", "checker-a"))
            .unwrap();
        fixture
            .store
            .handoff_token(&fixture.checker, handoff(3, "checker-a", "worker-a"))
            .unwrap();
        fixture
    }

    fn revisioned_start_request(
        &self,
        token_sequence: u64,
        from: &str,
        to: &str,
        cell_id: &str,
        payload_type: &str,
        adapter: &str,
    ) -> CommitDeliveryStartRequest {
        let message_id = format!("revisioned-message-{token_sequence}");
        let payload_sha256 = "b".repeat(64);
        let path = self
            ._root
            .path()
            .join(format!("revisioned-start-{token_sequence}.json"));
        fs::write(
            &path,
            serde_json::to_vec(&json!({
                "schema_version":"slk.native-start/v2",
                "status":"STARTED",
                "adapter":adapter,
                "run_id":"run-a",
                "cell_id":cell_id,
                "message_id":message_id,
                "request_sha256":payload_sha256,
                "native_request_sha256":"e".repeat(64),
                "observed_at":"2026-09-20T00:00:06Z",
                "process":{"pid":4321,"creation_time":format!("win-filetime:{token_sequence}")},
                "native_task":{"kind":adapter,"id":format!("task-{token_sequence}"),"status":"RUNNING"}
            }))
            .unwrap(),
        )
        .unwrap();
        let bytes = fs::read(&path).unwrap();
        let projection = self.store.query_run("run-a").unwrap();
        CommitDeliveryStartRequest {
            event_id: format!("revisioned-start-{token_sequence}"),
            transport_receipt_id: format!("revisioned-receipt-{token_sequence}"),
            run_id: "run-a".into(),
            go_id: "GO-001".into(),
            cell_id: cell_id.into(),
            attempt: if cell_id == "CELL-001" { 2 } else { 1 },
            plan_revision: projection.summary.current_plan_revision,
            expected_runtime_revision: projection.runtime_snapshot.unwrap().runtime_revision,
            message_id: message_id.clone(),
            token_sequence,
            from_role_instance_id: from.into(),
            to_role_instance_id: to.into(),
            endpoint_version: 1,
            payload_type: payload_type.into(),
            payload_sha256,
            start_evidence: DeliveryStartEvidence {
                evidence_id: format!("revisioned-evidence-{token_sequence}"),
                stored_path: path.to_string_lossy().into_owned(),
                sha256: format!("{:x}", Sha256::digest(bytes)),
                message_id,
                endpoint_sha256: "c".repeat(64),
                envelope_sha256: "d".repeat(64),
                native_status: NativeStartStatus::Started,
            },
            occurred_at: "2026-09-20T00:00:06Z".into(),
        }
    }
}

fn init_request(run_id: &str) -> InitRunRequest {
    InitRunRequest {
        project: ProjectIdentity {
            project_id: "project-a".into(),
            name: "Project A".into(),
            repository_url: None,
            last_known_path: "D:/ProjectA".into(),
        },
        run_id: run_id.into(),
        predecessor_run_id: None,
        run_name: Some("Concise Run".into()),
        run_description: Some("One bounded implementation outcome".into()),
        source_kind: Some("clk".into()),
        source_project_name: Some("LCapi 多模型接入".into()),
        goal: "Complete one bounded Run".into(),
        boundaries: json!({"write_scope":["src/"]}),
        go_nodes: vec![GoDefinition {
            go_id: "GO-001".into(),
            ordinal: 1,
            title: "GO".into(),
            objective: "Complete the work".into(),
        }],
        cell_nodes: vec![CellDefinition {
            go_id: "GO-001".into(),
            cell_id: "CELL-001".into(),
            ordinal: 1,
            title: "CELL".into(),
            objective: "Implement one bounded change".into(),
        }],
        supervisor: role("supervisor-a", Role::Supervisor),
        supervisor_endpoint: endpoint("session-supervisor-a"),
        occurred_at: "2026-09-20T00:00:00Z".into(),
    }
}

fn role_request(event_id: &str, role_instance_id: &str, role_kind: Role) -> RegisterRoleRequest {
    RegisterRoleRequest {
        event_id: event_id.into(),
        run_id: "run-a".into(),
        identity: role(role_instance_id, role_kind),
        endpoint: endpoint(&format!("session-{role_instance_id}")),
        occurred_at: "2026-09-20T00:00:01Z".into(),
    }
}

fn role(role_instance_id: &str, role: Role) -> RoleIdentity {
    RoleIdentity {
        role_instance_id: role_instance_id.into(),
        role,
        agent_runtime: match role {
            Role::Supervisor => "codex",
            Role::Overwatcher => "codex",
            Role::Checker => "ocrv",
            Role::Worker => "dsh",
        }
        .into(),
        provider: match role {
            Role::Supervisor | Role::Overwatcher => "openai",
            Role::Checker => "dashscope-tokenplan",
            Role::Worker => "deepseek",
        }
        .into(),
        model: match role {
            Role::Supervisor => "gpt-6.1-sol",
            Role::Overwatcher => "gpt-5.6-luna",
            Role::Checker => "qwen3.8-max",
            Role::Worker => "deepseek-v4-flash",
        }
        .into(),
        reasoning: match role {
            Role::Supervisor | Role::Overwatcher => "xhigh",
            Role::Checker | Role::Worker => "provider-default",
        }
        .into(),
        session_id: format!("session-{role_instance_id}"),
    }
}

fn endpoint(session_id: &str) -> EndpointIdentity {
    endpoint_v(session_id, 1)
}

fn endpoint_v(session_id: &str, endpoint_version: u32) -> EndpointIdentity {
    let transport_adapter = if session_id.contains("checker") {
        "ocrv-checker"
    } else if session_id.contains("worker") {
        "dsh-worker"
    } else {
        "codex-app-server"
    };
    EndpointIdentity {
        endpoint_version,
        transport_adapter: transport_adapter.into(),
        host_identity: "host-a".into(),
        session_id: session_id.into(),
        native_address: json!({"session_id":session_id}),
    }
}

fn handoff(sequence: u64, from: &str, to: &str) -> TokenHandoffRequest {
    TokenHandoffRequest {
        event_id: format!("token-{sequence}"),
        message_id: format!("message-{sequence}"),
        run_id: "run-a".into(),
        go_id: "GO-001".into(),
        cell_id: "CELL-001".into(),
        token_sequence: sequence,
        from_role_instance_id: from.into(),
        to_role_instance_id: to.into(),
        endpoint_version: 1,
        payload_type: "CELL_ASSIGNMENT".into(),
        payload_sha256: format!("hash-{sequence}"),
        payload_location: None,
        occurred_at: "2026-09-20T00:00:02Z".into(),
    }
}

fn event(event_id: &str, event_type: EventType, details: serde_json::Value) -> WriteRequest {
    WriteRequest {
        event_id: event_id.into(),
        run_id: "run-a".into(),
        go_id: Some("GO-001".into()),
        cell_id: Some("CELL-001".into()),
        attempt: Some(1),
        plan_revision: 1,
        role_instance_id: "worker-a".into(),
        event_type,
        details,
        corrects_event_id: None,
        occurred_at: "2026-09-20T00:00:03Z".into(),
    }
}

fn close_run(fixture: &Fixture) {
    let mut closed = event(
        "run-closed-for-role-close",
        EventType::RunClosed,
        json!({"outcome":"passed"}),
    );
    closed.role_instance_id = "supervisor-a".into();
    closed.go_id = None;
    closed.cell_id = None;
    closed.attempt = None;
    fixture
        .store
        .write_event(&fixture.supervisor, closed)
        .unwrap();
}

fn close_role_request(event_id: &str, role_instance_id: &str, role: Role) -> CloseRoleRequest {
    CloseRoleRequest {
        event_id: event_id.into(),
        run_id: "run-a".into(),
        role_instance_id: role_instance_id.into(),
        role,
        reason: "terminal Run member retirement".into(),
        occurred_at: "2026-09-20T00:00:04Z".into(),
    }
}
