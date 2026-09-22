use std::fs;

use rusqlite::Connection;
use serde_json::json;
use sha2::{Digest, Sha256};

use slk_state_core::auth::StateError;
use slk_state_core::model::{
    AdoptMethodContractRequest, BindOverwatcherRequest, CellDefinition, CloseOverwatcherRequest,
    CommitDeliveryStartRequest, DeliveryStartEvidence, EndpointIdentity, EventType,
    EvidenceReference, GoDefinition, InitRunRequest, MethodCompatibilityAssertions, NativeLiveness,
    NativeStartStatus, ObservationKind, ObservationMode, OperationalObservationRequest,
    OverwatchCheckResult, OverwatchCycleChecklist, OverwatchCycleRequest, OverwatcherAssertion,
    OverwatcherReplacementMode, OwnerAuthorizationEvidence, OwnerDecision, PreservedAssertion,
    ProjectIdentity, RecordOverwatcherStatusRequest, RegisterRoleRequest,
    ReplaceOverwatcherRequest, Role, RoleIdentity, TokenHandoffRequest, WriteRequest,
};
use slk_state_core::write::StateStore;

#[test]
fn completed_foreground_turn_blocks_new_423_dispatch() {
    let fixture = Fixture::new_423();
    let issued = fixture
        .store
        .bind_overwatcher(
            &fixture.supervisor,
            overwatcher_binding("run-a", "overwatcher-a", "session-overwatcher-a"),
        )
        .unwrap();
    let mut cycle = overwatch_cycle(1);
    cycle.runtime_revision = fixture
        .store
        .query_run("run-a")
        .unwrap()
        .runtime_snapshot
        .unwrap()
        .runtime_revision;
    cycle.evidence_refs = vec![fixture.evidence_ref("cycle-native.json", b"in progress")];
    cycle.native_active_session_evidence_ref = cycle.evidence_refs[0].path.clone();
    fixture
        .store
        .record_overwatch_cycle(&issued.credential, cycle)
        .unwrap();

    let status_evidence = fixture.evidence_ref("turn-completed.json", b"completed");
    fixture
        .store
        .record_overwatcher_status(
            &issued.credential,
            RecordOverwatcherStatusRequest {
                status_id: "status-completed-1".into(),
                run_id: "run-a".into(),
                binding_revision: 1,
                role_instance_id: "overwatcher-a".into(),
                session_id: "session-overwatcher-a".into(),
                foreground_turn_id: "foreground-turn-a".into(),
                native_liveness: NativeLiveness::Completed,
                evidence: status_evidence,
                observed_at: "2026-09-22T00:05:00Z".into(),
            },
        )
        .unwrap();

    assert!(matches!(
        fixture.store.commit_delivery_start(
            &fixture.supervisor,
            fixture.delivery_start_request("after-turn-end", "2026-09-22T00:05:01Z")
        ),
        Err(StateError::OverwatcherInactive(_))
    ));
}

#[test]
fn late_cycle_with_live_foreground_turn_is_not_false_inactive() {
    let fixture = Fixture::new_423();
    let issued = fixture
        .store
        .bind_overwatcher(
            &fixture.supervisor,
            overwatcher_binding("run-a", "overwatcher-a", "session-overwatcher-a"),
        )
        .unwrap();
    let revision = fixture
        .store
        .query_run("run-a")
        .unwrap()
        .runtime_snapshot
        .unwrap()
        .runtime_revision;
    let mut first = overwatch_cycle(1);
    first.runtime_revision = revision;
    first.evidence_refs = vec![fixture.evidence_ref("cycle-1.json", b"active")];
    first.native_active_session_evidence_ref = first.evidence_refs[0].path.clone();
    fixture
        .store
        .record_overwatch_cycle(&issued.credential, first)
        .unwrap();

    let mut late = overwatch_cycle(2);
    late.runtime_revision = revision;
    late.started_at = "2026-09-22T00:20:00Z".into();
    late.completed_at = "2026-09-22T00:20:01Z".into();
    late.next_cycle_at = "2026-09-22T00:24:01Z".into();
    late.evidence_refs = vec![fixture.evidence_ref("cycle-2.json", b"still active")];
    late.native_active_session_evidence_ref = late.evidence_refs[0].path.clone();
    fixture
        .store
        .record_overwatch_cycle(&issued.credential, late)
        .unwrap();

    fixture
        .store
        .commit_delivery_start(
            &fixture.supervisor,
            fixture.delivery_start_request("after-late-cycle", "2026-09-22T00:20:02Z"),
        )
        .unwrap();
}

#[test]
fn a_423_overwatcher_is_not_closed_at_a_cell_boundary() {
    let fixture = Fixture::new_423();
    let issued = fixture
        .store
        .bind_overwatcher(
            &fixture.supervisor,
            overwatcher_binding("run-a", "overwatcher-a", "session-overwatcher-a"),
        )
        .unwrap();
    let mut cycle = overwatch_cycle(1);
    cycle.runtime_revision = fixture.runtime_revision();
    cycle.evidence_refs = vec![fixture.evidence_ref("cycle-open.json", b"active")];
    cycle.native_active_session_evidence_ref = cycle.evidence_refs[0].path.clone();
    fixture
        .store
        .record_overwatch_cycle(&issued.credential, cycle)
        .unwrap();

    let result = fixture.store.close_overwatcher(
        &issued.credential,
        CloseOverwatcherRequest {
            event_id: "premature-overwatcher-close".into(),
            run_id: "run-a".into(),
            archive_evidence_ref: "codex:thread-archived:overwatcher-a".into(),
            final_cycle_id: Some("cycle-1".into()),
            runtime_revision: Some(fixture.runtime_revision()),
            occurred_at: "2026-09-22T00:05:00Z".into(),
        },
    );
    assert!(matches!(
        result,
        Err(StateError::OverwatcherObservationInvalid(_))
    ));
}

#[test]
fn a_423_terminal_close_requires_the_last_cycle_and_same_runtime_revision() {
    let fixture = Fixture::new_423();
    let issued = fixture
        .store
        .bind_overwatcher(
            &fixture.supervisor,
            overwatcher_binding("run-a", "overwatcher-a", "session-overwatcher-a"),
        )
        .unwrap();
    let mut first = overwatch_cycle(1);
    first.runtime_revision = fixture.runtime_revision();
    first.evidence_refs = vec![fixture.evidence_ref("cycle-first.json", b"active")];
    first.native_active_session_evidence_ref = first.evidence_refs[0].path.clone();
    fixture
        .store
        .record_overwatch_cycle(&issued.credential, first)
        .unwrap();
    fixture
        .store
        .write_event(
            &fixture.supervisor,
            WriteRequest {
                event_id: "run-closed-423".into(),
                run_id: "run-a".into(),
                go_id: None,
                cell_id: None,
                attempt: None,
                plan_revision: 1,
                role_instance_id: "supervisor-a".into(),
                event_type: EventType::RunClosed,
                details: json!({"reason":"validated terminal state"}),
                corrects_event_id: None,
                occurred_at: "2026-09-22T00:06:00Z".into(),
            },
        )
        .unwrap();
    let mut final_cycle = overwatch_cycle(2);
    final_cycle.runtime_revision = fixture.runtime_revision();
    final_cycle.latest_event_id = "run-closed-423".into();
    final_cycle.started_at = "2026-09-22T00:06:01Z".into();
    final_cycle.completed_at = "2026-09-22T00:06:02Z".into();
    final_cycle.next_cycle_at = "2026-09-22T00:10:02Z".into();
    final_cycle.evidence_refs = vec![fixture.evidence_ref("cycle-final.json", b"terminal")];
    final_cycle.native_active_session_evidence_ref = final_cycle.evidence_refs[0].path.clone();
    fixture
        .store
        .record_overwatch_cycle(&issued.credential, final_cycle)
        .unwrap();

    fixture
        .store
        .close_overwatcher(
            &issued.credential,
            CloseOverwatcherRequest {
                event_id: "terminal-overwatcher-close".into(),
                run_id: "run-a".into(),
                archive_evidence_ref: "codex:thread-archived:overwatcher-a".into(),
                final_cycle_id: Some("cycle-2".into()),
                runtime_revision: Some(fixture.runtime_revision()),
                occurred_at: "2026-09-22T00:06:03Z".into(),
            },
        )
        .unwrap();
    assert_eq!(
        fixture
            .store
            .query_run("run-a")
            .unwrap()
            .role("overwatcher"),
        None
    );
}

#[test]
fn planned_replacement_is_one_nonoverlapping_run_binding() {
    let fixture = Fixture::new_423();
    let issued = fixture
        .store
        .bind_overwatcher(
            &fixture.supervisor,
            overwatcher_binding("run-a", "overwatcher-a", "session-overwatcher-a"),
        )
        .unwrap();
    let mut cycle = overwatch_cycle(1);
    cycle.runtime_revision = fixture.runtime_revision();
    cycle.evidence_refs = vec![fixture.evidence_ref("cycle-replace.json", b"active")];
    cycle.native_active_session_evidence_ref = cycle.evidence_refs[0].path.clone();
    fixture
        .store
        .record_overwatch_cycle(&issued.credential, cycle)
        .unwrap();

    let replacement = fixture
        .store
        .replace_overwatcher(
            &fixture.supervisor,
            replacement_request(
                &fixture,
                OverwatcherReplacementMode::Planned,
                Some("cycle-1"),
                None,
            ),
        )
        .unwrap();
    assert_ne!(
        replacement.credential.expose_secret(),
        issued.credential.expose_secret()
    );
    let projection = fixture.store.query_run("run-a").unwrap();
    let watcher = projection.role("overwatcher").unwrap();
    assert_eq!(watcher.role_instance_id, "overwatcher-b");
    assert_eq!(projection.overwatcher_binding_transitions.len(), 2);
}

#[test]
fn dead_turn_recovery_preserves_and_resolves_the_incident_with_authorization() {
    let fixture = Fixture::new_423();
    let issued = fixture
        .store
        .bind_overwatcher(
            &fixture.supervisor,
            overwatcher_binding("run-a", "overwatcher-a", "session-overwatcher-a"),
        )
        .unwrap();
    let evidence = fixture.evidence_ref("dead-turn.json", b"completed");
    fixture
        .store
        .record_overwatcher_status(
            &issued.credential,
            RecordOverwatcherStatusRequest {
                status_id: "dead-turn-status".into(),
                run_id: "run-a".into(),
                binding_revision: 1,
                role_instance_id: "overwatcher-a".into(),
                session_id: "session-overwatcher-a".into(),
                foreground_turn_id: "foreground-turn-a".into(),
                native_liveness: NativeLiveness::Completed,
                evidence,
                observed_at: "2026-09-22T00:05:00Z".into(),
            },
        )
        .unwrap();

    fixture
        .store
        .replace_overwatcher(
            &fixture.supervisor,
            replacement_request(
                &fixture,
                OverwatcherReplacementMode::ContinuityRecovery,
                None,
                Some(fixture.evidence_ref("recovery-authorization.json", b"approved")),
            ),
        )
        .unwrap();
    let projection = fixture.store.query_run("run-a").unwrap();
    assert_eq!(projection.overwatcher_incident_transitions.len(), 3);
    assert_eq!(
        projection
            .overwatcher_incident_transitions
            .last()
            .unwrap()
            .state,
        "RESOLVED"
    );
}

#[test]
fn adoption_422_to_423_preserves_only_a_proven_active_run_watcher() {
    let fixture = Fixture::new();
    let issued = fixture
        .store
        .bind_overwatcher(
            &fixture.supervisor,
            overwatcher_binding("run-a", "overwatcher-a", "session-overwatcher-a"),
        )
        .unwrap();
    let mut cycle = overwatch_cycle(1);
    cycle.evidence_refs = vec![fixture.evidence_ref("adoption-live.json", b"active")];
    cycle.native_active_session_evidence_ref = cycle.evidence_refs[0].path.clone();
    fixture
        .store
        .record_overwatch_cycle(&issued.credential, cycle)
        .unwrap();
    let before = fixture.store.query_run("run-a").unwrap();
    let token = before.token_history.clone();

    let result = fixture
        .store
        .adopt_method_contract(
            &fixture.supervisor,
            adoption_423_request(&fixture, OverwatcherAssertion::PreservedActive),
        )
        .unwrap();
    assert_eq!(result.effective_version, "4.2.3");
    let after = fixture.store.query_run("run-a").unwrap();
    assert_eq!(after.token_history, token);
    assert_eq!(after.summary.slk_version, "4.2.3");
    assert_eq!(
        after
            .runtime_snapshot
            .unwrap()
            .overwatcher_status
            .as_deref(),
        Some("ACTIVE")
    );
}

#[test]
fn adoption_422_to_423_marks_an_unproven_watcher_for_explicit_recovery() {
    let fixture = Fixture::new();
    fixture
        .store
        .bind_overwatcher(
            &fixture.supervisor,
            overwatcher_binding("run-a", "overwatcher-a", "session-overwatcher-a"),
        )
        .unwrap();
    fixture
        .store
        .adopt_method_contract(
            &fixture.supervisor,
            adoption_423_request(&fixture, OverwatcherAssertion::ContinuityRecoveryRequired),
        )
        .unwrap();
    let after = fixture.store.query_run("run-a").unwrap();
    assert_eq!(
        after
            .runtime_snapshot
            .unwrap()
            .overwatcher_status
            .as_deref(),
        Some("VIOLATION")
    );
    assert_eq!(after.overwatcher_incident_transitions.len(), 1);
}

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
fn active_overwatcher_requires_an_adopted_supported_method_contract() {
    let fixture = Fixture::new();
    let database = Connection::open(fixture._root.path().join("slk.db")).unwrap();
    database
        .execute(
            "UPDATE runs SET slk_version='4.1.1', origin_slk_version='4.1.1'
             WHERE run_id='run-a'",
            [],
        )
        .unwrap();
    drop(database);

    assert!(matches!(
        fixture.store.bind_overwatcher(
            &fixture.supervisor,
            overwatcher_binding("run-a", "overwatcher-a", "session-overwatcher-a")
        ),
        Err(StateError::OverwatcherBindingInvalid(_))
    ));

    fixture
        .store
        .adopt_method_contract(
            &fixture.supervisor,
            adoption_request(&fixture.store, "4.1.1"),
        )
        .unwrap();
    fixture
        .store
        .bind_overwatcher(
            &fixture.supervisor,
            overwatcher_binding("run-a", "overwatcher-a", "session-overwatcher-a"),
        )
        .unwrap();
}

#[test]
fn method_adoption_rejects_an_already_active_overwatcher() {
    let fixture = Fixture::new();
    fixture
        .store
        .bind_overwatcher(
            &fixture.supervisor,
            overwatcher_binding("run-a", "overwatcher-a", "session-overwatcher-a"),
        )
        .unwrap();
    assert!(fixture
        .store
        .adopt_method_contract(
            &fixture.supervisor,
            adoption_request(&fixture.store, "4.2.1")
        )
        .is_err());
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
                final_cycle_id: None,
                runtime_revision: None,
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

    fn new_423() -> Self {
        let fixture = Self::new();
        let database = slk_state_core::schema::open_database(fixture._root.path()).unwrap();
        database
            .execute(
                "UPDATE runs SET slk_version='4.2.3' WHERE run_id='run-a'",
                [],
            )
            .unwrap();
        drop(database);
        fixture
    }

    fn evidence_ref(&self, name: &str, bytes: &[u8]) -> EvidenceReference {
        let path = self._root.path().join(name);
        fs::write(&path, bytes).unwrap();
        EvidenceReference {
            path: path.to_string_lossy().into_owned(),
            sha256: format!("{:x}", Sha256::digest(bytes)),
        }
    }

    fn delivery_start_request(
        &self,
        suffix: &str,
        occurred_at: &str,
    ) -> CommitDeliveryStartRequest {
        let evidence = self.evidence_ref(&format!("start-{suffix}.json"), b"started");
        CommitDeliveryStartRequest {
            event_id: format!("transport-started-{suffix}"),
            transport_receipt_id: format!("start-receipt-{suffix}"),
            run_id: "run-a".into(),
            go_id: "GO-001".into(),
            cell_id: "CELL-001".into(),
            attempt: 1,
            plan_revision: 1,
            expected_runtime_revision: self
                .store
                .query_run("run-a")
                .unwrap()
                .runtime_snapshot
                .unwrap()
                .runtime_revision,
            message_id: format!("message-{suffix}"),
            token_sequence: 2,
            from_role_instance_id: "supervisor-a".into(),
            to_role_instance_id: "checker-a".into(),
            endpoint_version: 1,
            payload_type: "CELL_ASSIGNMENT".into(),
            payload_sha256: "c".repeat(64),
            start_evidence: DeliveryStartEvidence {
                evidence_id: format!("start-evidence-{suffix}"),
                stored_path: evidence.path,
                sha256: evidence.sha256,
                message_id: format!("message-{suffix}"),
                endpoint_sha256: "d".repeat(64),
                envelope_sha256: "e".repeat(64),
                native_status: NativeStartStatus::Started,
            },
            occurred_at: occurred_at.into(),
        }
    }

    fn runtime_revision(&self) -> u64 {
        self.store
            .query_run("run-a")
            .unwrap()
            .runtime_snapshot
            .unwrap()
            .runtime_revision
    }
}

fn replacement_request(
    fixture: &Fixture,
    mode: OverwatcherReplacementMode,
    final_cycle_id: Option<&str>,
    authorization_evidence: Option<EvidenceReference>,
) -> ReplaceOverwatcherRequest {
    ReplaceOverwatcherRequest {
        event_id: format!("replace-overwatcher-{}", mode.as_str().to_ascii_lowercase()),
        run_id: "run-a".into(),
        mode,
        expected_binding_revision: 1,
        expected_runtime_revision: fixture.runtime_revision(),
        final_cycle_id: final_cycle_id.map(str::to_string),
        replacement: role("overwatcher-b", Role::Overwatcher, "session-overwatcher-b"),
        endpoint: endpoint("session-overwatcher-b"),
        cadence_seconds: 240,
        foreground_turn_id: "foreground-turn-b".into(),
        native_active_session_evidence: fixture.evidence_ref("replacement-live.json", b"active"),
        authorization_evidence,
        reason: "preserve one whole-Run watcher through an explicit transition".into(),
        occurred_at: "2026-09-22T00:05:01Z".into(),
    }
}

fn adoption_423_request(
    fixture: &Fixture,
    overwatcher: OverwatcherAssertion,
) -> AdoptMethodContractRequest {
    AdoptMethodContractRequest {
        receipt_id: "adopt-run-a-423".into(),
        run_id: "run-a".into(),
        expected_snapshot: fixture.store.run_state_snapshot("run-a").unwrap(),
        from_version: "4.2.2".into(),
        to_version: "4.2.3".into(),
        owner_authorization: OwnerAuthorizationEvidence {
            source_thread_id: "owner-thread-423".into(),
            message_id: "owner-message-423".into(),
            content_sha256: "a".repeat(64),
            decision: OwnerDecision::ApproveMethodContractAdoption,
            occurred_at: "2026-09-22T00:06:00Z".into(),
        },
        reconciliation_receipt_id: None,
        compatibility: MethodCompatibilityAssertions {
            topology: PreservedAssertion::Preserved,
            role_bindings: PreservedAssertion::Preserved,
            token: PreservedAssertion::Preserved,
            engineering_history: PreservedAssertion::Preserved,
            overwatcher,
        },
        reason: "adopt the revisioned 4.2.3 runtime contract without changing engineering history"
            .into(),
        occurred_at: "2026-09-22T00:06:01Z".into(),
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
        binding_revision: 1,
        canonical_task_id: format!("task-{run_id}"),
        reason: "Supervisor selected one dedicated observation Session".into(),
        occurred_at: "2026-09-22T00:00:01Z".into(),
    }
}

fn adoption_request(store: &StateStore, from_version: &str) -> AdoptMethodContractRequest {
    AdoptMethodContractRequest {
        receipt_id: "adoption-overwatcher-gate".into(),
        run_id: "run-a".into(),
        expected_snapshot: store.run_state_snapshot("run-a").unwrap(),
        from_version: from_version.into(),
        to_version: "4.2.2".into(),
        owner_authorization: OwnerAuthorizationEvidence {
            source_thread_id: "owner-thread".into(),
            message_id: "owner-message".into(),
            content_sha256: "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
                .into(),
            decision: OwnerDecision::ApproveMethodContractAdoption,
            occurred_at: "2026-09-22T00:00:01Z".into(),
        },
        reconciliation_receipt_id: None,
        compatibility: MethodCompatibilityAssertions {
            topology: PreservedAssertion::Preserved,
            role_bindings: PreservedAssertion::Preserved,
            token: PreservedAssertion::Preserved,
            engineering_history: PreservedAssertion::Preserved,
            overwatcher: OverwatcherAssertion::Absent,
        },
        reason: "Adopt active Overwatcher contract".into(),
        occurred_at: "2026-09-22T00:00:02Z".into(),
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
        binding_revision: 1,
        runtime_revision: 1,
        native_liveness: NativeLiveness::InProgress,
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
            EvidenceReference {
                path: "state:run-a:revision-1".into(),
                sha256: "a".repeat(64),
            },
            EvidenceReference {
                path: "codex:foreground-turn:foreground-turn-a".into(),
                sha256: "b".repeat(64),
            },
        ],
        cost_metrics: None,
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
