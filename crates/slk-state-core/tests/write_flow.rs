use serde_json::json;

use slk_state_core::auth::StateError;
use slk_state_core::model::{
    CellDefinition, EndpointIdentity, EventType, GoDefinition, InitRunRequest, ProjectIdentity,
    RebindSessionRequest, RegisterRoleRequest, ReplaceRoleRequest, RevisePlanRequest, Role,
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
fn session_rebound_retires_the_old_endpoint_and_preserves_the_role_credential() {
    let fixture = Fixture::new();
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
        supervisor_endpoint: endpoint("thread-supervisor"),
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
            Role::Checker => "ocrv",
            Role::Worker => "dsh",
        }
        .into(),
        provider: "provider".into(),
        model: "model".into(),
        reasoning: "high".into(),
        session_id: format!("session-{role_instance_id}"),
    }
}

fn endpoint(session_id: &str) -> EndpointIdentity {
    endpoint_v(session_id, 1)
}

fn endpoint_v(session_id: &str, endpoint_version: u32) -> EndpointIdentity {
    EndpointIdentity {
        endpoint_version,
        transport_adapter: "native-cli".into(),
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
