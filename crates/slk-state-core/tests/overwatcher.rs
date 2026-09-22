use rusqlite::Connection;
use serde_json::json;

use slk_state_core::auth::StateError;
use slk_state_core::model::{
    BindOverwatcherRequest, CellDefinition, CloseOverwatcherRequest, EndpointIdentity, EventType,
    GoDefinition, InitRunRequest, ObservationKind, ObservationMode, OperationalObservationRequest,
    OverwatchCheckResult, OverwatchCycleChecklist, OverwatchCycleRequest, ProjectIdentity,
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

    let fixture = Fixture::new();
    let mut invalid_cadence =
        overwatcher_binding("run-a", "overwatcher-a", "session-overwatcher-a");
    invalid_cadence.cadence_seconds = 120;
    assert!(matches!(
        fixture
            .store
            .bind_overwatcher(&fixture.supervisor, invalid_cadence),
        Err(StateError::OverwatcherBindingInvalid(_))
    ));

    let fixture = Fixture::new();
    let mut missing_active_turn =
        overwatcher_binding("run-a", "overwatcher-a", "session-overwatcher-a");
    missing_active_turn.foreground_turn_id.clear();
    missing_active_turn
        .native_active_session_evidence_ref
        .clear();
    assert!(matches!(
        fixture
            .store
            .bind_overwatcher(&fixture.supervisor, missing_active_turn),
        Err(StateError::OverwatcherBindingInvalid(_))
    ));
}

#[test]
fn active_overwatcher_records_one_complete_monotonic_cycle() {
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
        .record_overwatch_cycle(&issued.credential, overwatch_cycle(1))
        .unwrap();

    let projection = fixture.store.query_run("run-a").unwrap();
    assert_eq!(projection.overwatch_cycles.len(), 1);
    assert_eq!(projection.overwatch_cycles[0].cycle_sequence, 1);
    assert_eq!(projection.overwatch_cycles[0].cadence_seconds, 240);
    assert_eq!(
        projection.overwatch_cycles[0].foreground_turn_id,
        "foreground-turn-a"
    );
}

#[test]
fn overwatch_cycle_rejects_wrong_session_incomplete_checklist_and_reused_sequence() {
    let fixture = Fixture::new();
    let issued = fixture
        .store
        .bind_overwatcher(
            &fixture.supervisor,
            overwatcher_binding("run-a", "overwatcher-a", "session-overwatcher-a"),
        )
        .unwrap();

    let mut wrong_session = overwatch_cycle(1);
    wrong_session.session_id = "another-session".into();
    assert!(matches!(
        fixture
            .store
            .record_overwatch_cycle(&issued.credential, wrong_session),
        Err(StateError::OverwatcherCycleInvalid(_))
    ));

    let mut incomplete = overwatch_cycle(1);
    incomplete.checklist.active_session = OverwatchCheckResult::NotApplicable;
    assert!(matches!(
        fixture
            .store
            .record_overwatch_cycle(&issued.credential, incomplete),
        Err(StateError::OverwatcherCycleInvalid(_))
    ));

    fixture
        .store
        .record_overwatch_cycle(&issued.credential, overwatch_cycle(1))
        .unwrap();
    let mut reused_sequence = overwatch_cycle(1);
    reused_sequence.cycle_id = "cycle-reused".into();
    assert!(matches!(
        fixture
            .store
            .record_overwatch_cycle(&issued.credential, reused_sequence),
        Err(StateError::OverwatcherCycleSequence { .. })
    ));
    assert!(matches!(
        fixture
            .store
            .record_overwatch_cycle(&issued.credential, overwatch_cycle(2)),
        Err(StateError::OverwatcherCycleInvalid(message)) if message.contains("overlap")
    ));
}

#[test]
fn bound_overwatcher_requires_fresh_cycles_before_new_handoffs() {
    let fixture = Fixture::new();
    let issued = fixture
        .store
        .bind_overwatcher(
            &fixture.supervisor,
            overwatcher_binding("run-a", "overwatcher-a", "session-overwatcher-a"),
        )
        .unwrap();

    assert!(matches!(
        fixture.store.handoff_token(
            &fixture.supervisor,
            handoff_at(2, "supervisor-a", "checker-a", "2026-09-22T00:00:02Z")
        ),
        Err(StateError::OverwatcherInactive(_))
    ));

    fixture
        .store
        .record_overwatch_cycle(&issued.credential, overwatch_cycle(1))
        .unwrap();
    fixture
        .store
        .handoff_token(
            &fixture.supervisor,
            handoff_at(2, "supervisor-a", "checker-a", "2026-09-22T00:07:59Z"),
        )
        .unwrap();

    assert!(matches!(
        fixture.store.handoff_token(
            &fixture.checker,
            handoff_at(3, "checker-a", "worker-a", "2026-09-22T00:12:01Z")
        ),
        Err(StateError::OverwatcherInactive(_))
    ));
}

#[test]
fn legacy_4_2_binding_is_not_silently_reinterpreted_as_active() {
    let fixture = Fixture::new();
    let database = Connection::open(fixture._root.path().join("slk.db")).unwrap();
    database
        .execute(
            "INSERT INTO overwatcher_bindings
             (run_id, role_instance_id, agent_runtime, provider, model, reasoning,
              session_id, endpoint_version, transport_adapter, host_identity,
              native_address_json, bound_by_role_instance_id, binding_reason,
              credential_id, credential_sha256, credential_state, lifecycle_state, bound_at)
             VALUES ('run-a','legacy-overwatcher','codex','openai','gpt-5.6-sol','xhigh',
                     'legacy-session',1,'codex-app-server','host-a','{}','supervisor-a',
                     'legacy 4.2 binding','legacy-credential',
                     'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
                     'active','active','2026-09-22T00:00:01Z')",
            [],
        )
        .unwrap();
    drop(database);

    assert!(matches!(
        fixture.store.handoff_token(
            &fixture.supervisor,
            handoff_at(2, "supervisor-a", "checker-a", "2026-09-22T00:00:02Z")
        ),
        Err(StateError::OverwatcherInactive(message)) if message.contains("legacy 4.2.0")
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
        observation_mode: ObservationMode::ForegroundActiveTurn,
        cadence_seconds: 240,
        foreground_turn_id: "foreground-turn-a".into(),
        native_active_session_evidence_ref: "codex:thread-active:overwatcher-a".into(),
        reason: "Supervisor selected one dedicated observation Session".into(),
        occurred_at: "2026-09-22T00:00:01Z".into(),
    }
}

fn overwatch_cycle(cycle_sequence: u64) -> OverwatchCycleRequest {
    OverwatchCycleRequest {
        cycle_id: format!("cycle-{cycle_sequence}"),
        run_id: "run-a".into(),
        plan_revision: 1,
        role_instance_id: "overwatcher-a".into(),
        session_id: "session-overwatcher-a".into(),
        foreground_turn_id: "foreground-turn-a".into(),
        cycle_sequence,
        cadence_seconds: 240,
        go_id: Some("GO-001".into()),
        cell_id: Some("CELL-001".into()),
        attempt: Some(1),
        token_sequence: 1,
        token_holder_role_instance_id: "supervisor-a".into(),
        latest_event_id: "bind-overwatcher-a".into(),
        latest_message_id: None,
        checklist: OverwatchCycleChecklist {
            run_position: OverwatchCheckResult::Clear,
            role_bindings: OverwatchCheckResult::Clear,
            direct_handoffs: OverwatchCheckResult::Clear,
            cell_lifecycle: OverwatchCheckResult::Clear,
            stall_and_duplicates: OverwatchCheckResult::Clear,
            bi_projection: OverwatchCheckResult::Clear,
            active_session: OverwatchCheckResult::Clear,
            terminal_closure: OverwatchCheckResult::NotApplicable,
        },
        anomaly_codes: Vec::new(),
        evidence_refs: vec![
            "state:run-a:revision-1".into(),
            "codex:foreground-turn:foreground-turn-a".into(),
        ],
        native_active_session_evidence_ref: "codex:thread-active:overwatcher-a".into(),
        started_at: "2026-09-22T00:03:59Z".into(),
        completed_at: "2026-09-22T00:04:00Z".into(),
        next_cycle_at: "2026-09-22T00:08:00Z".into(),
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
        agent_runtime: match role {
            Role::Supervisor | Role::Overwatcher => "codex",
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
            Role::Supervisor | Role::Overwatcher => "gpt-5.6-sol",
            Role::Checker => "qwen3.8-max",
            Role::Worker => "deepseek-v4-flash",
        }
        .into(),
        reasoning: match role {
            Role::Supervisor | Role::Overwatcher => "xhigh",
            Role::Checker | Role::Worker => "provider-default",
        }
        .into(),
        session_id: session_id.into(),
    }
}

fn endpoint(session_id: &str) -> EndpointIdentity {
    let transport_adapter = if session_id.contains("checker") {
        "ocrv-checker"
    } else if session_id.contains("worker") {
        "dsh-worker"
    } else {
        "codex-app-server"
    };
    EndpointIdentity {
        endpoint_version: 1,
        transport_adapter: transport_adapter.into(),
        host_identity: "host-a".into(),
        session_id: session_id.into(),
        native_address: json!({"session_id":session_id}),
    }
}

fn handoff(sequence: u64, from: &str, to: &str) -> TokenHandoffRequest {
    handoff_at(sequence, from, to, "2026-09-22T00:00:02Z")
}

fn handoff_at(sequence: u64, from: &str, to: &str, occurred_at: &str) -> TokenHandoffRequest {
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
        occurred_at: occurred_at.into(),
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
