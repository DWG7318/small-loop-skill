use serde_json::json;
use sha2::{Digest, Sha256};

use slk_state_core::auth::StateError;
use slk_state_core::model::{
    CellDefinition, CloseRoleRequest, EndpointIdentity, EventType, GoDefinition, InitRunRequest,
    ProjectIdentity, RebindSessionRequest, RegisterRoleRequest, ReplaceRoleRequest,
    RevisePlanRequest, Role, RoleIdentity, TokenHandoffRequest, WriteRequest,
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
    let fixture = Fixture::new();
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
fn owner_selected_supervisor_sol_family_is_not_fixed_to_one_generation() {
    let root = tempfile::tempdir().unwrap();
    let store = StateStore::new(root.path());
    let mut selected = init_request("run-a");
    selected.supervisor.model = "gpt-6.1-sol".into();
    store.init_run(selected).unwrap();

    let root = tempfile::tempdir().unwrap();
    let store = StateStore::new(root.path());
    let mut wrong_class = init_request("run-b");
    wrong_class.supervisor.model = "gpt-6-luna".into();
    assert!(matches!(
        store.init_run(wrong_class),
        Err(StateError::RoleBindingInvalid { .. })
    ));
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
    let mut escaped = handoff(3, "checker-a", "supervisor-a");
    escaped.payload_type = "D1_FAILURE_ESCALATION".into();
    assert!(matches!(
        fixture.store.handoff_token(&fixture.checker, escaped),
        Err(StateError::InvalidTokenRoute { .. })
    ));
    assert!(matches!(
        fixture
            .store
            .handoff_token(&fixture.checker, handoff(3, "checker-a", "worker-a")),
        Err(StateError::InvalidTokenRoute { .. })
    ));
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

struct Fixture {
    _root: tempfile::TempDir,
    store: StateStore,
    supervisor: slk_state_core::auth::Credential,
    checker: slk_state_core::auth::Credential,
    worker: slk_state_core::auth::Credential,
}

impl Fixture {
    fn new() -> Self {
        let root = tempfile::tempdir().unwrap();
        let store = StateStore::new(root.path());
        let initialized = store.init_run(init_request("run-a")).unwrap();
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
            Role::Supervisor => "gpt-5.6-sol",
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
