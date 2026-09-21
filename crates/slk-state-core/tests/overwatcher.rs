use serde_json::json;

use slk_state_core::auth::StateError;
use slk_state_core::model::{
    BindOverwatcherRequest, CellDefinition, CloseOverwatcherRequest, EndpointIdentity, EventType,
    GoDefinition, InitRunRequest, ObservationKind, OperationalObservationRequest, ProjectIdentity,
    RegisterRoleRequest, Role, RoleIdentity, TokenHandoffRequest, WriteRequest,
};
use slk_state_core::write::StateStore;

#[test]
fn a_run_without_overwatcher_keeps_the_original_peer_handoff_path() {
    let fixture = Fixture::new();
    assert!(fixture
        .store
        .query_run("run-a")
        .unwrap()
        .role("overwatcher")
        .is_none());

    fixture
        .store
        .handoff_token(&fixture.supervisor, handoff(2, "supervisor-a", "checker-a"))
        .unwrap();
    fixture
        .store
        .handoff_token(&fixture.checker, handoff(3, "checker-a", "worker-a"))
        .unwrap();

    let token = fixture.store.current_token("run-a").unwrap();
    assert_eq!(token.sequence, 3);
    assert_eq!(token.owner_role_instance_id, "worker-a");
}

#[test]
fn supervisor_binds_at_most_one_optional_overwatcher_without_moving_token() {
    let fixture = Fixture::new();
    let before = fixture.store.current_token("run-a").unwrap();
    let issued = fixture
        .store
        .bind_overwatcher(
            &fixture.supervisor,
            overwatcher_binding("run-a", "overwatcher-a", "session-overwatcher-a"),
        )
        .unwrap();

    let projection = fixture.store.query_run("run-a").unwrap();
    let overwatcher = projection.role("overwatcher").unwrap();
    assert_eq!(overwatcher.role_instance_id, "overwatcher-a");
    assert_eq!(
        overwatcher.binding_mode.as_deref(),
        Some("supervisor_selected")
    );
    assert_eq!(fixture.store.current_token("run-a").unwrap(), before);
    assert!(!format!("{:?}", issued.credential).contains("slk_"));

    assert!(matches!(
        fixture.store.bind_overwatcher(
            &fixture.supervisor,
            overwatcher_binding("run-a", "overwatcher-b", "session-overwatcher-b"),
        ),
        Err(StateError::OverwatcherAlreadyBound)
    ));
}

#[test]
fn binding_requires_the_current_supervisor_and_a_dedicated_unreused_session() {
    let fixture = Fixture::new();
    let wrong_role = fixture.store.bind_overwatcher(
        &fixture.checker,
        overwatcher_binding("run-a", "overwatcher-a", "session-overwatcher-a"),
    );
    assert!(matches!(
        wrong_role,
        Err(StateError::OverwatcherBindingNotAuthorized)
    ));

    let mut wrong_identity = overwatcher_binding("run-a", "overwatcher-a", "session-overwatcher-a");
    wrong_identity.identity.role = Role::Worker;
    assert!(matches!(
        fixture
            .store
            .bind_overwatcher(&fixture.supervisor, wrong_identity),
        Err(StateError::OverwatcherBindingInvalid(_))
    ));

    fixture
        .store
        .bind_overwatcher(
            &fixture.supervisor,
            overwatcher_binding("run-a", "overwatcher-a", "session-overwatcher-a"),
        )
        .unwrap();

    let mut second = init_request("run-b", "supervisor-b");
    second.occurred_at = "2026-09-22T01:00:00Z".into();
    let second_run = fixture.store.init_run(second).unwrap();
    assert!(matches!(
        fixture.store.bind_overwatcher(
            &second_run.supervisor_credential,
            overwatcher_binding("run-b", "overwatcher-b", "session-overwatcher-a"),
        ),
        Err(StateError::OverwatcherSessionReused)
    ));
}

#[test]
fn binding_rejects_incomplete_identity_endpoint_and_event_fields() {
    let fixture = Fixture::new();
    let mut missing_event = overwatcher_binding("run-a", "overwatcher-a", "session-overwatcher-a");
    missing_event.event_id.clear();
    assert!(matches!(
        fixture
            .store
            .bind_overwatcher(&fixture.supervisor, missing_event),
        Err(StateError::OverwatcherBindingInvalid(_))
    ));

    let fixture = Fixture::new();
    let mut missing_session = overwatcher_binding("run-a", "overwatcher-a", "session-a");
    missing_session.identity.session_id.clear();
    missing_session.endpoint.session_id.clear();
    assert!(matches!(
        fixture
            .store
            .bind_overwatcher(&fixture.supervisor, missing_session),
        Err(StateError::OverwatcherBindingInvalid(_))
    ));

    let fixture = Fixture::new();
    let mut missing_model = overwatcher_binding("run-a", "overwatcher-a", "session-a");
    missing_model.identity.model.clear();
    assert!(matches!(
        fixture
            .store
            .bind_overwatcher(&fixture.supervisor, missing_model),
        Err(StateError::OverwatcherBindingInvalid(_))
    ));
}

#[test]
fn overwatcher_records_operations_but_cannot_author_engineering_or_token_facts() {
    let fixture = Fixture::new();
    let issued = fixture
        .store
        .bind_overwatcher(
            &fixture.supervisor,
            overwatcher_binding("run-a", "overwatcher-a", "session-overwatcher-a"),
        )
        .unwrap();

    let mut d1 = event("forged-d1", EventType::D1Passed, "overwatcher-a");
    d1.details = json!({"verdict":"PASS"});
    assert!(matches!(
        fixture.store.write_event(&issued.credential, d1),
        Err(StateError::RoleNotAuthorized { .. })
    ));
    assert!(matches!(
        fixture
            .store
            .handoff_token(&issued.credential, handoff(2, "overwatcher-a", "checker-a")),
        Err(StateError::RoleNotAuthorized { .. })
    ));

    let observation = observation(
        "observation-a",
        ObservationKind::ActivityUnproven,
        json!({"reason":"no fresh native execution evidence"}),
    );
    fixture
        .store
        .record_observation(&issued.credential, observation.clone())
        .unwrap();
    fixture
        .store
        .record_observation(&issued.credential, observation)
        .unwrap();

    let projection = fixture.store.query_run("run-a").unwrap();
    assert_eq!(projection.operational_observations.len(), 1);
    assert_eq!(
        projection.operational_observations[0].kind,
        "ACTIVITY_UNPROVEN"
    );
    assert_eq!(fixture.store.current_token("run-a").unwrap().sequence, 1);
}

#[test]
fn observation_identity_conflicts_fail_closed_and_do_not_overwrite_history() {
    let fixture = Fixture::new();
    let issued = fixture
        .store
        .bind_overwatcher(
            &fixture.supervisor,
            overwatcher_binding("run-a", "overwatcher-a", "session-overwatcher-a"),
        )
        .unwrap();

    fixture
        .store
        .record_observation(
            &issued.credential,
            observation(
                "observation-a",
                ObservationKind::DeliveryRetrying,
                json!({"attempt":1}),
            ),
        )
        .unwrap();
    assert!(matches!(
        fixture.store.record_observation(
            &issued.credential,
            observation(
                "observation-a",
                ObservationKind::DeliveryRetrying,
                json!({"attempt":2}),
            ),
        ),
        Err(StateError::OverwatcherObservationConflict)
    ));

    let projection = fixture.store.query_run("run-a").unwrap();
    assert_eq!(projection.operational_observations.len(), 1);
    assert_eq!(
        projection.operational_observations[0].details_json,
        r#"{"attempt":1}"#
    );
}

#[test]
fn overwatcher_closes_itself_without_closing_or_advancing_the_run() {
    let fixture = Fixture::new();
    let issued = fixture
        .store
        .bind_overwatcher(
            &fixture.supervisor,
            overwatcher_binding("run-a", "overwatcher-a", "session-overwatcher-a"),
        )
        .unwrap();
    fixture
        .store
        .close_overwatcher(
            &issued.credential,
            CloseOverwatcherRequest {
                event_id: "overwatcher-closed".into(),
                run_id: "run-a".into(),
                archive_evidence_ref: "codex-thread-archived:overwatcher-a".into(),
                occurred_at: "2026-09-22T00:10:00Z".into(),
            },
        )
        .unwrap();

    let projection = fixture.store.query_run("run-a").unwrap();
    assert!(projection.role("overwatcher").is_none());
    assert_eq!(projection.summary.closure_state, "open");
    assert_eq!(fixture.store.current_token("run-a").unwrap().sequence, 1);
}

struct Fixture {
    _root: tempfile::TempDir,
    store: StateStore,
    supervisor: slk_state_core::auth::Credential,
    checker: slk_state_core::auth::Credential,
}

impl Fixture {
    fn new() -> Self {
        let root = tempfile::tempdir().unwrap();
        let store = StateStore::new(root.path());
        let initialized = store
            .init_run(init_request("run-a", "supervisor-a"))
            .unwrap();
        let checker = store
            .register_role(
                &initialized.supervisor_credential,
                register_role("run-a", "checker-a", Role::Checker),
            )
            .unwrap();
        store
            .register_role(
                &checker.credential,
                register_role("run-a", "worker-a", Role::Worker),
            )
            .unwrap();
        Self {
            _root: root,
            store,
            supervisor: initialized.supervisor_credential,
            checker: checker.credential,
        }
    }
}

fn init_request(run_id: &str, supervisor_id: &str) -> InitRunRequest {
    InitRunRequest {
        project: ProjectIdentity {
            project_id: "project-a".into(),
            name: "Project A".into(),
            repository_url: None,
            last_known_path: "D:/ProjectA".into(),
        },
        run_id: run_id.into(),
        predecessor_run_id: None,
        run_name: Some("Overwatcher Run".into()),
        run_description: Some("One bounded serial Run".into()),
        source_kind: Some("clk".into()),
        source_project_name: Some("LCaS".into()),
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
        supervisor: role(
            supervisor_id,
            Role::Supervisor,
            &format!("session-{supervisor_id}"),
        ),
        supervisor_endpoint: endpoint(&format!("session-{supervisor_id}")),
        occurred_at: "2026-09-22T00:00:00Z".into(),
    }
}

fn overwatcher_binding(
    run_id: &str,
    role_instance_id: &str,
    session_id: &str,
) -> BindOverwatcherRequest {
    BindOverwatcherRequest {
        event_id: format!("bind-{role_instance_id}"),
        run_id: run_id.into(),
        identity: role(role_instance_id, Role::Overwatcher, session_id),
        endpoint: endpoint(session_id),
        reason: "Supervisor selected one dedicated observation Session".into(),
        occurred_at: "2026-09-22T00:00:01Z".into(),
    }
}

fn observation(
    observation_id: &str,
    kind: ObservationKind,
    details: serde_json::Value,
) -> OperationalObservationRequest {
    OperationalObservationRequest {
        observation_id: observation_id.into(),
        run_id: "run-a".into(),
        go_id: Some("GO-001".into()),
        cell_id: Some("CELL-001".into()),
        attempt: Some(1),
        plan_revision: 1,
        role_instance_id: "overwatcher-a".into(),
        kind,
        related_event_id: None,
        message_id: Some("message-a".into()),
        evidence_refs: vec!["transport/message-a/started.json".into()],
        details,
        occurred_at: "2026-09-22T00:00:02Z".into(),
    }
}

fn register_role(run_id: &str, role_instance_id: &str, role_kind: Role) -> RegisterRoleRequest {
    RegisterRoleRequest {
        event_id: format!("register-{role_instance_id}"),
        run_id: run_id.into(),
        identity: role(
            role_instance_id,
            role_kind,
            &format!("session-{role_instance_id}"),
        ),
        endpoint: endpoint(&format!("session-{role_instance_id}")),
        occurred_at: "2026-09-22T00:00:01Z".into(),
    }
}

fn role(role_instance_id: &str, role: Role, session_id: &str) -> RoleIdentity {
    RoleIdentity {
        role_instance_id: role_instance_id.into(),
        role,
        agent_runtime: "codex".into(),
        provider: "openai".into(),
        model: "gpt-5.6-sol".into(),
        reasoning: "xhigh".into(),
        session_id: session_id.into(),
    }
}

fn endpoint(session_id: &str) -> EndpointIdentity {
    EndpointIdentity {
        endpoint_version: 1,
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
        occurred_at: "2026-09-22T00:00:02Z".into(),
    }
}

fn event(event_id: &str, event_type: EventType, role_instance_id: &str) -> WriteRequest {
    WriteRequest {
        event_id: event_id.into(),
        run_id: "run-a".into(),
        go_id: Some("GO-001".into()),
        cell_id: Some("CELL-001".into()),
        attempt: Some(1),
        plan_revision: 1,
        role_instance_id: role_instance_id.into(),
        event_type,
        details: json!({}),
        corrects_event_id: None,
        occurred_at: "2026-09-22T00:00:02Z".into(),
    }
}
