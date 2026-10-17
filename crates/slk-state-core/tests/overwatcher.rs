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
    OverwatchAnomalyCode, OverwatchCheckResult, OverwatchCycleChecklist, OverwatchCycleRequest,
    OverwatcherAssertion, OverwatcherReplacementMode, OwnerAuthorizationEvidence, OwnerDecision,
    PreservedAssertion, ProjectIdentity, RebindSessionRequest, RecordOverwatcherStatusRequest,
    RegisterRoleRequest, ReplaceOverwatcherRequest, ResumeOverwatcherTurnRequest, Role,
    RoleIdentity, RotateOverwatcherCredentialRequest, TokenHandoffRequest, WriteRequest,
};
use slk_state_core::write::StateStore;

#[test]
fn current_443_central_writes_keep_long_original_identifiers() {
    let root = tempfile::tempdir().unwrap();
    let store = StateStore::new(root.path());
    let run_id = format!("run-{}", "r".repeat(512));
    let supervisor_id = format!("supervisor-{}", "s".repeat(512));
    let checker_id = format!("checker-{}", "c".repeat(512));
    let initialized = store
        .init_run(init_request(&run_id, &supervisor_id))
        .unwrap();
    let mut registration = register_role(&run_id, &checker_id, Role::Checker);
    registration.event_id = format!("register-{}", "e".repeat(512));
    store
        .register_role(&initialized.supervisor_credential, registration)
        .unwrap();
    let current = store.query_run(&run_id).unwrap();
    assert_eq!(current.summary.run_id, run_id);
    assert!(current
        .roles
        .iter()
        .any(|role| role.role_instance_id == supervisor_id));
    assert!(current
        .roles
        .iter()
        .any(|role| role.role_instance_id == checker_id));

    let mut invalid = register_role(&run_id, "invalid/checker", Role::Checker);
    invalid.event_id = "invalid\\event".into();
    assert!(store
        .register_role(&initialized.supervisor_credential, invalid)
        .is_err());
    assert_eq!(
        store.query_run(&run_id).unwrap().roles.len(),
        current.roles.len()
    );
}

#[test]
fn current_overwatcher_does_not_require_a_fabricated_reasoning_setting() {
    let root=tempfile::tempdir().unwrap();let store=StateStore::new(root.path());
    let supervisor=store.init_run(init_request("run-a","supervisor-a")).unwrap().supervisor_credential;
    let mut binding=subagent_binding("run-a","overwatcher-a","/root/ow");
    binding.identity.reasoning.clear();
    binding.identity.model="owner-selected-child-model".into();
    let mut unsupported=binding.clone();unsupported.endpoint.transport_adapter="unknown-adapter".into();
    assert!(store.bind_overwatcher(&supervisor,unsupported).is_err());
    store.bind_overwatcher(&supervisor,binding).unwrap();
    let run=store.query_run("run-a").unwrap();
    assert_eq!(run.role("overwatcher").unwrap().reasoning,"");
}

#[test]
fn current_release_can_admit_its_registered_overwatcher_without_relabeling_history() {
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
    let mut binding = subagent_binding("run-a", "overwatcher-a", "session-overwatcher-a");
    binding.cadence_seconds = 300;
    assert!(store
        .bind_overwatcher(&initialized.supervisor_credential, binding.clone())
        .is_err());
    binding.cadence_seconds = 600;
    store
        .bind_overwatcher(&initialized.supervisor_credential, binding)
        .unwrap();
    let current = store.query_run("run-a").unwrap();
    assert_eq!(current.summary.slk_version, env!("CARGO_PKG_VERSION"));
    assert_eq!(current.summary.origin_slk_version, env!("CARGO_PKG_VERSION"));

    let second = store
        .init_run(init_request("run-b", "supervisor-b"))
        .unwrap();
    let mut shared = subagent_binding("run-b", "overwatcher-b", "session-overwatcher-a");
    shared.endpoint.native_address =
        subagent_address("session-supervisor-b", "session-overwatcher-a");
    shared.cadence_seconds = 600;
    shared.native_active_session_evidence_ref = "run-b/independent-native-proof.json".into();
    let mut wrong_host = shared.clone();
    wrong_host.endpoint.host_identity = "different-real-host".into();
    wrong_host.endpoint.native_address["parent"]["host_identity"] = json!("different-real-host");
    assert!(matches!(
        store.bind_overwatcher(&second.supervisor_credential, wrong_host),
        Err(StateError::OverwatcherBindingInvalid(_))
    ));
    store
        .bind_overwatcher(&second.supervisor_credential, shared)
        .unwrap();
    let other = store.query_run("run-b").unwrap();
    assert_eq!(
        other.role("overwatcher").unwrap().session_id,
        "session-overwatcher-a"
    );
    assert!(other.events.iter().any(|event| event
        .details_json
        .contains("run-b/independent-native-proof.json")));
}

#[test]
fn supervisor_rebinds_overwatcher_endpoint_without_changing_role_or_session() {
    let fixture = Fixture::new_440();
    let mut binding = overwatcher_binding("run-a", "overwatcher-a", "session-overwatcher-a");
    binding.cadence_seconds = 600;
    fixture
        .store
        .bind_overwatcher(&fixture.supervisor, binding)
        .unwrap();
    let before = fixture.store.query_run("run-a").unwrap();
    let before_runtime = before.runtime_snapshot.unwrap().runtime_revision;
    let mut wrong_session = endpoint("different-overwatcher-session");
    wrong_session.endpoint_version = 2;
    assert!(matches!(
        fixture.store.rebind_session(
            &fixture.supervisor,
            RebindSessionRequest {
                event_id: "rebind-overwatcher-wrong-session".into(),
                run_id: "run-a".into(),
                role_instance_id: "overwatcher-a".into(),
                endpoint: wrong_session,
                reason: "must not replace the registered OW Session".into(),
                occurred_at: "2026-10-05T00:59:00Z".into(),
            },
        ),
        Err(StateError::RoleBindingInvalid { .. })
    ));
    let mut rebound = endpoint("session-overwatcher-a");
    rebound.endpoint_version = 2;
    rebound.native_address =
        json!({"desktop_thread_id":"session-overwatcher-a","caller_pipe":"app-tools"});

    fixture
        .store
        .rebind_session(
            &fixture.supervisor,
            RebindSessionRequest {
                event_id: "rebind-overwatcher-desktop".into(),
                run_id: "run-a".into(),
                role_instance_id: "overwatcher-a".into(),
                endpoint: rebound,
                reason: "replace stale CLI endpoint with the same native Desktop Session".into(),
                occurred_at: "2026-10-05T01:00:00Z".into(),
            },
        )
        .unwrap();

    let after = fixture.store.query_run("run-a").unwrap();
    let watcher = after.role("overwatcher").unwrap();
    assert_eq!(watcher.role_instance_id, "overwatcher-a");
    assert_eq!(watcher.session_id, "session-overwatcher-a");
    assert_eq!(watcher.endpoints[0].endpoint_version, 2);
    assert_eq!(
        after.runtime_snapshot.unwrap().runtime_revision,
        before_runtime + 1
    );
    let event = after
        .events
        .iter()
        .find(|row| row.event_id == "rebind-overwatcher-desktop")
        .unwrap();
    assert_eq!(event.event_type, "SESSION_REBOUND");
    assert!(event.details_json.contains("previous_endpoint"));
}

#[test]
fn overwatcher_binding_preserves_latest_engineering_message() {
    let fixture = Fixture::new_423();
    fixture
        .store
        .commit_delivery_start(
            &fixture.supervisor,
            fixture.delivery_start_request("before-overwatcher-binding", "2026-09-22T00:00:02Z"),
        )
        .unwrap();
    let before = fixture
        .store
        .query_run("run-a")
        .unwrap()
        .runtime_snapshot
        .unwrap();
    assert_eq!(
        before.latest_message_id.as_deref(),
        Some("message-before-overwatcher-binding")
    );

    fixture
        .store
        .bind_overwatcher(
            &fixture.supervisor,
            overwatcher_binding("run-a", "overwatcher-a", "session-overwatcher-a"),
        )
        .unwrap();

    let after = fixture
        .store
        .query_run("run-a")
        .unwrap()
        .runtime_snapshot
        .unwrap();
    assert_eq!(after.latest_event_id, "bind-overwatcher-a");
    assert_eq!(after.latest_message_id, before.latest_message_id);
}

#[test]
fn supervisor_rotates_only_the_exact_active_overwatcher_credential_without_a_cycle() {
    let fixture = Fixture::new_427();
    let issued = fixture
        .store
        .bind_overwatcher(
            &fixture.supervisor,
            overwatcher_binding("run-a", "overwatcher-a", "session-overwatcher-a"),
        )
        .unwrap();
    let before = fixture.store.query_run("run-a").unwrap();
    assert!(before.overwatch_cycles.is_empty());

    let request = credential_rotation_request(&fixture, &issued.credential_id);
    let rotated = fixture
        .store
        .rotate_overwatcher_credential(&fixture.supervisor, request.clone())
        .unwrap();

    assert_eq!(rotated.binding_revision, 1);
    assert_eq!(
        rotated.runtime_revision,
        before.runtime_snapshot.unwrap().runtime_revision + 1
    );
    assert_ne!(rotated.issued.credential_id, issued.credential_id);
    assert_eq!(
        fixture
            .store
            .authenticate_active_role("run-a", &rotated.issued.credential)
            .unwrap()
            .role_instance_id,
        "overwatcher-a"
    );
    assert!(matches!(
        fixture
            .store
            .authenticate_active_role("run-a", &issued.credential),
        Err(StateError::CredentialInvalid)
    ));
    assert!(matches!(
        fixture.store.authenticate_active_role(
            "run-a",
            &slk_state_core::auth::Credential::from_secret(issued.credential_id.clone())
        ),
        Err(StateError::CredentialInvalid)
    ));

    let after = fixture.store.query_run("run-a").unwrap();
    assert_eq!(after.token_history, before.token_history);
    assert_eq!(after.events, before.events);
    let watcher = after.role("overwatcher").unwrap();
    assert_eq!(watcher.role_instance_id, "overwatcher-a");
    assert_eq!(watcher.session_id, "session-overwatcher-a");
    assert!(after.overwatch_cycles.is_empty());
    let database = slk_state_core::schema::open_database(fixture._root.path()).unwrap();
    let receipt: (String, String, u64) = database
        .query_row(
            "SELECT old_credential_id, new_credential_id, runtime_revision
             FROM overwatcher_credential_rotations WHERE rotation_id=?1",
            [&request.rotation_id],
            |row| Ok((row.get(0)?, row.get(1)?, row.get(2)?)),
        )
        .unwrap();
    assert_eq!(receipt.0, issued.credential_id);
    assert_eq!(receipt.1, rotated.issued.credential_id);
    assert_eq!(receipt.2, rotated.runtime_revision);
    assert_ne!(receipt.1, rotated.issued.credential.expose_secret());

    assert!(matches!(
        fixture
            .store
            .rotate_overwatcher_credential(&fixture.supervisor, request),
        Err(StateError::OverwatcherCredentialRotationNotReplayable)
    ));
}

#[test]
fn overwatcher_credential_rotation_fails_closed_for_wrong_authority_or_stale_identity() {
    let fixture = Fixture::new_427();
    let issued = fixture
        .store
        .bind_overwatcher(
            &fixture.supervisor,
            overwatcher_binding("run-a", "overwatcher-a", "session-overwatcher-a"),
        )
        .unwrap();
    let request = credential_rotation_request(&fixture, &issued.credential_id);

    assert!(matches!(
        fixture
            .store
            .rotate_overwatcher_credential(&fixture.checker, request.clone()),
        Err(StateError::OverwatcherBindingNotAuthorized)
    ));

    let mut stale = request.clone();
    stale.expected_runtime_revision -= 1;
    assert!(matches!(
        fixture
            .store
            .rotate_overwatcher_credential(&fixture.supervisor, stale),
        Err(StateError::OverwatcherBindingInvalid(_))
    ));

    let mut wrong_session = request;
    wrong_session.session_id = "different-session".into();
    assert!(matches!(
        fixture
            .store
            .rotate_overwatcher_credential(&fixture.supervisor, wrong_session),
        Err(StateError::OverwatcherBindingInvalid(_))
    ));

    let request = credential_rotation_request(&fixture, &issued.credential_id);
    for invalid in [
        RotateOverwatcherCredentialRequest {
            expected_binding_revision: 2,
            ..request.clone()
        },
        RotateOverwatcherCredentialRequest {
            role_instance_id: "different-overwatcher".into(),
            ..request.clone()
        },
        RotateOverwatcherCredentialRequest {
            foreground_turn_id: "different-turn".into(),
            ..request.clone()
        },
        RotateOverwatcherCredentialRequest {
            expected_overwatcher_credential_id: "credential-different".into(),
            ..request.clone()
        },
    ] {
        assert!(matches!(
            fixture
                .store
                .rotate_overwatcher_credential(&fixture.supervisor, invalid),
            Err(StateError::OverwatcherBindingInvalid(_))
        ));
    }

    let database = slk_state_core::schema::open_database(fixture._root.path()).unwrap();
    database
        .execute(
            "UPDATE overwatcher_bindings SET continuity_state='VIOLATION' WHERE run_id='run-a'",
            [],
        )
        .unwrap();
    drop(database);
    assert!(matches!(
        fixture
            .store
            .rotate_overwatcher_credential(&fixture.supervisor, request),
        Err(StateError::OverwatcherBindingInvalid(_))
    ));
}

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
fn a_440_overwatcher_cannot_close_before_d2_passes() {
    let fixture = Fixture::new_440();
    let mut binding = overwatcher_binding("run-a", "overwatcher-a", "session-overwatcher-a");
    binding.cadence_seconds = 600;
    let issued = fixture
        .store
        .bind_overwatcher(&fixture.supervisor, binding)
        .unwrap();

    let result = fixture.store.close_overwatcher(
        &issued.credential,
        CloseOverwatcherRequest {
            event_id: "premature-440-overwatcher-close".into(),
            run_id: "run-a".into(),
            archive_evidence_ref: "codex:thread-archived:overwatcher-a".into(),
            final_cycle_id: None,
            runtime_revision: None,
            occurred_at: "2026-10-04T00:01:00Z".into(),
        },
    );
    assert!(matches!(
        result,
        Err(StateError::OverwatcherObservationInvalid(_))
    ));
}

#[test]
fn a_440_d2_snapshot_closes_overwatcher_before_run_without_changing_engineering_state() {
    let fixture = Fixture::new_440();
    let mut binding = overwatcher_binding("run-a", "overwatcher-a", "session-overwatcher-a");
    binding.cadence_seconds = 600;
    let issued = fixture
        .store
        .bind_overwatcher(&fixture.supervisor, binding)
        .unwrap();
    fixture
        .store
        .write_event(
            &fixture.supervisor,
            WriteRequest {
                event_id: "d2-passed-440".into(),
                run_id: "run-a".into(),
                go_id: None,
                cell_id: None,
                attempt: None,
                plan_revision: 1,
                role_instance_id: "supervisor-a".into(),
                event_type: EventType::D2Passed,
                details: json!({"verdict":"PASS"}),
                corrects_event_id: None,
                occurred_at: "2026-10-04T00:01:00Z".into(),
            },
        )
        .unwrap();
    let before = fixture.store.query_run("run-a").unwrap();
    let snapshot = before.runtime_snapshot.unwrap();
    let token = fixture.store.current_token("run-a").unwrap();
    let mut final_cycle = overwatch_cycle(1);
    final_cycle.cadence_seconds = 600;
    final_cycle.next_cycle_at = "2026-09-22T00:14:00Z".into();
    final_cycle.runtime_revision = snapshot.runtime_revision;
    final_cycle.latest_event_id = snapshot.latest_event_id;
    final_cycle.latest_message_id = snapshot.latest_message_id;
    final_cycle.token_sequence = token.sequence;
    final_cycle.token_holder_role_instance_id = token.owner_role_instance_id.clone();
    final_cycle.checklist.terminal_closure = OverwatchCheckResult::Clear;
    final_cycle.evidence_refs =
        vec![fixture.evidence_ref("cycle-final-440.json", b"d2 terminal snapshot")];
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
                event_id: "terminal-overwatcher-close-440".into(),
                run_id: "run-a".into(),
                archive_evidence_ref: "codex:thread-archived:overwatcher-a".into(),
                final_cycle_id: Some("cycle-1".into()),
                runtime_revision: Some(snapshot.runtime_revision),
                occurred_at: "2026-10-04T00:01:02Z".into(),
            },
        )
        .unwrap();
    let after_overwatcher = fixture.store.query_run("run-a").unwrap();
    assert_eq!(after_overwatcher.summary.closure_state, "open");
    assert!(after_overwatcher.role("overwatcher").is_none());
    assert_eq!(fixture.store.current_token("run-a").unwrap(), token);
    fixture
        .store
        .write_event(
            &fixture.supervisor,
            WriteRequest {
                event_id: "run-closed-440".into(),
                run_id: "run-a".into(),
                go_id: None,
                cell_id: None,
                attempt: None,
                plan_revision: 1,
                role_instance_id: "supervisor-a".into(),
                event_type: EventType::RunClosed,
                details: json!({"reason":"validated terminal state"}),
                corrects_event_id: None,
                occurred_at: "2026-10-04T00:01:03Z".into(),
            },
        )
        .unwrap();
    assert_eq!(
        fixture
            .store
            .query_run("run-a")
            .unwrap()
            .summary
            .closure_state,
        "closed"
    );
    assert_eq!(fixture.store.current_token("run-a").unwrap(), token);
}

#[test]
fn a_440_terminal_race_resumes_same_session_then_finalizes_before_run_close() {
    let fixture = Fixture::new_440();
    let mut binding = overwatcher_binding("run-a", "overwatcher-a", "session-overwatcher-a");
    binding.cadence_seconds = 600;
    let issued = fixture
        .store
        .bind_overwatcher(&fixture.supervisor, binding)
        .unwrap();
    fixture
        .store
        .record_overwatcher_status(
            &issued.credential,
            RecordOverwatcherStatusRequest {
                status_id: "terminal-turn-ended-440".into(),
                run_id: "run-a".into(),
                binding_revision: 1,
                role_instance_id: "overwatcher-a".into(),
                session_id: "session-overwatcher-a".into(),
                foreground_turn_id: "foreground-turn-a".into(),
                native_liveness: NativeLiveness::Completed,
                evidence: fixture.evidence_ref("terminal-turn-ended-440.json", b"turn ended"),
                observed_at: "2026-10-04T00:00:59Z".into(),
            },
        )
        .unwrap();
    fixture
        .store
        .resume_overwatcher_turn(
            &fixture.supervisor,
            ResumeOverwatcherTurnRequest {
                event_id: "resume-terminal-turn-440".into(),
                run_id: "run-a".into(),
                role_instance_id: "overwatcher-a".into(),
                session_id: "session-overwatcher-a".into(),
                binding_revision: 1,
                expected_runtime_revision: fixture.runtime_revision(),
                previous_foreground_turn_id: "foreground-turn-a".into(),
                foreground_turn_id: "foreground-turn-b".into(),
                last_anomaly_cycle_id: None,
                last_native_status_id: Some("terminal-turn-ended-440".into()),
                native_active_session_evidence: fixture
                    .evidence_ref("resume-terminal-turn-440.json", b"same session active"),
                reason: "finish the terminal cycle in the same bound Session".into(),
                occurred_at: "2026-10-04T00:01:00Z".into(),
            },
        )
        .unwrap();
    fixture
        .store
        .write_event(
            &fixture.supervisor,
            WriteRequest {
                event_id: "d2-passed-race-440".into(),
                run_id: "run-a".into(),
                go_id: None,
                cell_id: None,
                attempt: None,
                plan_revision: 1,
                role_instance_id: "supervisor-a".into(),
                event_type: EventType::D2Passed,
                details: json!({"verdict":"PASS"}),
                corrects_event_id: None,
                occurred_at: "2026-10-04T00:01:01Z".into(),
            },
        )
        .unwrap();
    let snapshot = fixture
        .store
        .query_run("run-a")
        .unwrap()
        .runtime_snapshot
        .unwrap();
    let mut final_cycle = overwatch_cycle(1);
    final_cycle.cadence_seconds = 600;
    final_cycle.next_cycle_at = "2026-09-22T00:14:00Z".into();
    final_cycle.foreground_turn_id = "foreground-turn-b".into();
    final_cycle.runtime_revision = snapshot.runtime_revision;
    final_cycle.latest_event_id = snapshot.latest_event_id;
    final_cycle.latest_message_id = snapshot.latest_message_id;
    final_cycle.checklist.terminal_closure = OverwatchCheckResult::Clear;
    final_cycle.evidence_refs =
        vec![fixture.evidence_ref("cycle-final-race-440.json", b"terminal")];
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
                event_id: "terminal-race-overwatcher-close-440".into(),
                run_id: "run-a".into(),
                archive_evidence_ref: "codex:thread-archived:overwatcher-a".into(),
                final_cycle_id: Some("cycle-1".into()),
                runtime_revision: Some(snapshot.runtime_revision),
                occurred_at: "2026-10-04T00:01:03Z".into(),
            },
        )
        .unwrap();
    fixture
        .store
        .write_event(
            &fixture.supervisor,
            WriteRequest {
                event_id: "run-closed-race-440".into(),
                run_id: "run-a".into(),
                go_id: None,
                cell_id: None,
                attempt: None,
                plan_revision: 1,
                role_instance_id: "supervisor-a".into(),
                event_type: EventType::RunClosed,
                details: json!({"reason":"validated terminal state"}),
                corrects_event_id: None,
                occurred_at: "2026-10-04T00:01:04Z".into(),
            },
        )
        .unwrap();
    let projection = fixture.store.query_run("run-a").unwrap();
    assert_eq!(projection.summary.closure_state, "closed");
    assert!(projection.role("overwatcher").is_none());
    assert_eq!(projection.overwatcher_binding_transitions.len(), 2);
}

#[test]
fn preclose_keeps_d2_valid_after_ow_restore_but_not_after_new_engineering() {
    for later_engineering in [false, true] {
        let fixture = Fixture::new_440();
        let mut binding = overwatcher_binding("run-a", "overwatcher-a", "session-overwatcher-a");
        binding.cadence_seconds = 600;
        let issued = fixture.store.bind_overwatcher(&fixture.supervisor, binding).unwrap();
        fixture.store.write_event(&fixture.supervisor, WriteRequest {
            go_id: None, cell_id: None, attempt: None,
            details: json!({"verdict":"PASS"}),
            ..event("d2-before-restore", EventType::D2Passed, "supervisor-a")
        }).unwrap();
        let d2 = fixture.store.query_run("run-a").unwrap().runtime_snapshot.unwrap();
        fixture.store.record_overwatcher_status(&issued.credential, RecordOverwatcherStatusRequest {
            status_id: "ow-ended-after-d2".into(), run_id: "run-a".into(),
            binding_revision: 1, role_instance_id: "overwatcher-a".into(),
            session_id: "session-overwatcher-a".into(), foreground_turn_id: "foreground-turn-a".into(),
            native_liveness: NativeLiveness::Completed,
            evidence: fixture.evidence_ref("ow-ended.json", b"ended"),
            observed_at: "2026-09-22T00:02:00Z".into(),
        }).unwrap();
        fixture.store.resume_overwatcher_turn(&fixture.supervisor, ResumeOverwatcherTurnRequest {
            event_id: "ow-restored-after-d2".into(), run_id: "run-a".into(),
            role_instance_id: "overwatcher-a".into(), session_id: "session-overwatcher-a".into(),
            binding_revision: 1, expected_runtime_revision: fixture.runtime_revision(),
            previous_foreground_turn_id: "foreground-turn-a".into(), foreground_turn_id: "foreground-turn-b".into(),
            last_anomaly_cycle_id: None, last_native_status_id: Some("ow-ended-after-d2".into()),
            native_active_session_evidence: fixture.evidence_ref("ow-restored.json", b"restored"),
            reason: "finish final observation after D2".into(),
            occurred_at: "2026-09-22T00:02:01Z".into(),
        }).unwrap();
        if later_engineering {
            fixture.store.write_event(&fixture.supervisor, WriteRequest {
                go_id: None, cell_id: None, attempt: None,
                details: json!({"verdict":"FAIL"}),
                ..event("d2-invalidated", EventType::D2Failed, "supervisor-a")
            }).unwrap();
        }
        let snapshot = fixture.store.query_run("run-a").unwrap().runtime_snapshot.unwrap();
        assert!(snapshot.runtime_revision > d2.runtime_revision);
        assert_eq!(snapshot.token_sequence, d2.token_sequence);
        let mut cycle = overwatch_cycle(1);
        cycle.cadence_seconds = 600;
        cycle.next_cycle_at = "2026-09-22T00:14:00Z".into();
        cycle.foreground_turn_id = "foreground-turn-b".into();
        cycle.runtime_revision = snapshot.runtime_revision;
        cycle.latest_event_id = snapshot.latest_event_id.clone();
        cycle.latest_message_id = snapshot.latest_message_id;
        cycle.evidence_refs = vec![fixture.evidence_ref("final-after-restore.json", b"current observation")];
        cycle.native_active_session_evidence_ref = cycle.evidence_refs[0].path.clone();
        fixture.store.record_overwatch_cycle(&issued.credential, cycle).unwrap();
        let request = CloseOverwatcherRequest {
            event_id: "close-after-restore".into(), run_id: "run-a".into(),
            archive_evidence_ref: "archive-binding-only".into(), final_cycle_id: Some("cycle-1".into()),
            runtime_revision: Some(snapshot.runtime_revision), occurred_at: "2026-09-22T00:04:01Z".into(),
        };
        let mut stale = request.clone();
        stale.runtime_revision = Some(d2.runtime_revision);
        assert!(fixture.store.close_overwatcher(&issued.credential, stale).is_err());
        let result = fixture.store.close_overwatcher(&issued.credential, request);
        if later_engineering {
            assert!(matches!(result, Err(StateError::OverwatcherObservationInvalid(_))));
        } else {
            result.unwrap();
            let current = fixture.store.query_run("run-a").unwrap();
            assert_eq!(current.summary.closure_state, "open");
            assert!(current.role("overwatcher").is_none());
            assert_eq!(current.runtime_snapshot.unwrap().token_sequence, d2.token_sequence);
        }
    }
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
    let mut late = overwatch_cycle(2);
    late.runtime_revision = fixture.runtime_revision();
    late.started_at = "2026-09-22T00:20:00Z".into();
    late.completed_at = "2026-09-22T00:20:01Z".into();
    late.next_cycle_at = "2026-09-22T00:24:01Z".into();
    late.evidence_refs = vec![fixture.evidence_ref("cycle-late.json", b"still active")];
    late.native_active_session_evidence_ref = late.evidence_refs[0].path.clone();
    fixture
        .store
        .record_overwatch_cycle(&issued.credential, late)
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
                occurred_at: "2026-09-22T00:20:02Z".into(),
            },
        )
        .unwrap();
    let mut final_cycle = overwatch_cycle(3);
    final_cycle.runtime_revision = fixture.runtime_revision();
    final_cycle.latest_event_id = "run-closed-423".into();
    final_cycle.started_at = "2026-09-22T00:20:03Z".into();
    final_cycle.completed_at = "2026-09-22T00:20:04Z".into();
    final_cycle.next_cycle_at = "2026-09-22T00:24:04Z".into();
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
                final_cycle_id: Some("cycle-3".into()),
                runtime_revision: Some(fixture.runtime_revision()),
                occurred_at: "2026-09-22T00:20:05Z".into(),
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
    let database = slk_state_core::schema::open_database(fixture._root.path()).unwrap();
    let binding_count: i64 = database
        .query_row(
            "SELECT COUNT(*) FROM overwatcher_bindings WHERE run_id='run-a'",
            [],
            |row| row.get(0),
        )
        .unwrap();
    let (cycle_count, session_count, turn_count): (i64, i64, i64) = database
        .query_row(
            "SELECT COUNT(*), COUNT(DISTINCT session_id), COUNT(DISTINCT foreground_turn_id)
             FROM overwatch_cycles WHERE run_id='run-a'",
            [],
            |row| Ok((row.get(0)?, row.get(1)?, row.get(2)?)),
        )
        .unwrap();
    let late_health: (String, String) = database
        .query_row(
            "SELECT cadence_health, native_liveness FROM overwatch_cycles WHERE cycle_id='cycle-2'",
            [],
            |row| Ok((row.get(0)?, row.get(1)?)),
        )
        .unwrap();
    let model_change_event_count: i64 = database
        .query_row(
            "SELECT COUNT(*) FROM work_events
             WHERE run_id='run-a' AND event_type='MODEL_CHANGED'",
            [],
            |row| row.get(0),
        )
        .unwrap();
    assert_eq!(
        (binding_count, cycle_count, session_count, turn_count),
        (1, 3, 1, 1)
    );
    assert_eq!(late_health, ("LATE".into(), "IN_PROGRESS".into()));
    assert_eq!(model_change_event_count, 0);
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
fn replacement_projection_binds_the_original_request_and_exposes_only_credential_id() {
    let fixture = Fixture::new_423();
    let issued = fixture.store.bind_overwatcher(&fixture.supervisor,
        overwatcher_binding("run-a", "overwatcher-a", "session-overwatcher-a")).unwrap();
    let mut cycle = overwatch_cycle(1);
    cycle.runtime_revision = fixture.runtime_revision();
    cycle.evidence_refs = vec![fixture.evidence_ref("replacement-projection.json", b"active")];
    cycle.native_active_session_evidence_ref = cycle.evidence_refs[0].path.clone();
    fixture.store.record_overwatch_cycle(&issued.credential, cycle).unwrap();
    let request = replacement_request(&fixture, OverwatcherReplacementMode::Planned,
        Some("cycle-1"), None);
    let mut request_json = serde_json::to_value(&request).unwrap();
    request_json["endpoint"]["native_address"]["unicode"] = json!("观察员 / 🚀");
    request_json["endpoint"]["native_address"]["small_number"] = json!(1e-7);
    let raw = serde_json::to_vec_pretty(&request_json).unwrap();
    let expected_hash = format!("{:x}", Sha256::digest(&raw));
    let new_credential = fixture.store.replace_overwatcher_json(&fixture.supervisor, &raw).unwrap();
    let projection = serde_json::to_value(fixture.store.query_run("run-a").unwrap()).unwrap();
    let event = projection["events"].as_array().unwrap().iter()
        .find(|event| event["event_id"] == request.event_id).expect("replacement audit event");
    assert_eq!(event["author_role_instance_id"], "supervisor-a");
    assert_eq!(event["event_type"], "OVERWATCHER_REPLACED");
    let details: serde_json::Value = serde_json::from_str(event["details_json"].as_str().unwrap()).unwrap();
    assert_eq!(details["request_sha256"], expected_hash);
    assert_eq!(details["overwatcher_role_instance_id"], "overwatcher-b");
    assert_eq!(details["binding_revision"], 2);
    let watcher = projection["roles"].as_array().unwrap().iter()
        .find(|role| role["role"] == "overwatcher").unwrap();
    assert_eq!(watcher["credential_id"], new_credential.credential_id);
    assert!(!projection.to_string().contains(new_credential.credential.expose_secret()));
    assert!(fixture.store.replace_overwatcher(&fixture.supervisor, request).is_err());
}

#[test]
fn replacement_audit_event_preserves_d2_but_never_masks_later_engineering() {
    for later_engineering in [false, true] {
        let fixture = Fixture::new_440();
        let mut binding = overwatcher_binding("run-a", "overwatcher-a", "session-overwatcher-a");
        binding.cadence_seconds = 600;
        let issued = fixture.store.bind_overwatcher(&fixture.supervisor, binding).unwrap();
        fixture.store.write_event(&fixture.supervisor, WriteRequest {
            go_id: None, cell_id: None, attempt: None, details: json!({"verdict":"PASS"}),
            ..event("d2-before-replacement", EventType::D2Passed, "supervisor-a")
        }).unwrap();
        let token = fixture.store.current_token("run-a").unwrap();
        fixture.store.record_overwatcher_status(&issued.credential, RecordOverwatcherStatusRequest {
            status_id: "ow-ended-after-d2".into(), run_id: "run-a".into(), binding_revision: 1,
            role_instance_id: "overwatcher-a".into(), session_id: "session-overwatcher-a".into(),
            foreground_turn_id: "foreground-turn-a".into(), native_liveness: NativeLiveness::Completed,
            evidence: fixture.evidence_ref("ow-ended.json", b"ended"),
            observed_at: "2026-09-22T00:02:00Z".into(),
        }).unwrap();
        let mut replacement = replacement_request(&fixture, OverwatcherReplacementMode::ContinuityRecovery,
            None, Some(fixture.evidence_ref("replacement-authorized.json", b"approved")));
        replacement.cadence_seconds = 600;
        let new_credential = fixture.store.replace_overwatcher(&fixture.supervisor, replacement).unwrap();
        if later_engineering {
            fixture.store.write_event(&fixture.supervisor, WriteRequest {
                go_id: None, cell_id: None, attempt: None, details: json!({"verdict":"FAIL"}),
                ..event("d2-after-replacement-failed", EventType::D2Failed, "supervisor-a")
            }).unwrap();
        }
        let snapshot = fixture.store.query_run("run-a").unwrap().runtime_snapshot.unwrap();
        let mut cycle = overwatch_cycle(1);
        cycle.role_instance_id = "overwatcher-b".into();
        cycle.session_id = "session-overwatcher-b".into();
        cycle.foreground_turn_id = "foreground-turn-b".into();
        cycle.binding_revision = 2;
        cycle.cadence_seconds = 600;
        cycle.next_cycle_at = "2026-09-22T00:14:00Z".into();
        cycle.runtime_revision = snapshot.runtime_revision;
        cycle.latest_event_id = snapshot.latest_event_id;
        cycle.latest_message_id = snapshot.latest_message_id;
        cycle.evidence_refs = vec![fixture.evidence_ref("final-after-replacement.json", b"current")];
        cycle.native_active_session_evidence_ref = cycle.evidence_refs[0].path.clone();
        fixture.store.record_overwatch_cycle(&new_credential.credential, cycle).unwrap();
        let result = fixture.store.close_overwatcher(&new_credential.credential, CloseOverwatcherRequest {
            event_id: "close-after-replacement".into(), run_id: "run-a".into(),
            archive_evidence_ref: "archive-binding-only".into(), final_cycle_id: Some("cycle-1".into()),
            runtime_revision: Some(snapshot.runtime_revision), occurred_at: "2026-09-22T00:04:01Z".into(),
        });
        if later_engineering {
            assert!(matches!(result, Err(StateError::OverwatcherObservationInvalid(_))));
        } else {
            result.unwrap();
        }
        assert_eq!(fixture.store.current_token("run-a").unwrap(), token);
    }
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
fn adoption_423_to_424_preserves_a_proven_active_overwatcher() {
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
    cycle.latest_event_id = fixture
        .store
        .query_run("run-a")
        .unwrap()
        .runtime_snapshot
        .unwrap()
        .latest_event_id;
    cycle.evidence_refs = vec![fixture.evidence_ref("adoption-424-live.json", b"active")];
    cycle.native_active_session_evidence_ref = cycle.evidence_refs[0].path.clone();
    fixture
        .store
        .record_overwatch_cycle(&issued.credential, cycle)
        .unwrap();

    let result = fixture
        .store
        .adopt_method_contract(
            &fixture.supervisor,
            adoption_424_request(&fixture, OverwatcherAssertion::PreservedActive),
        )
        .unwrap();

    assert_eq!(result.effective_version, "4.2.4");
    let after = fixture.store.query_run("run-a").unwrap();
    assert_eq!(after.summary.slk_version, "4.2.4");
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
fn adoption_424_to_425_preserves_a_proven_active_overwatcher() {
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
    cycle.latest_event_id = fixture
        .store
        .query_run("run-a")
        .unwrap()
        .runtime_snapshot
        .unwrap()
        .latest_event_id;
    cycle.evidence_refs = vec![fixture.evidence_ref("adoption-425-live.json", b"active")];
    cycle.native_active_session_evidence_ref = cycle.evidence_refs[0].path.clone();
    fixture
        .store
        .record_overwatch_cycle(&issued.credential, cycle)
        .unwrap();
    fixture
        .store
        .adopt_method_contract(
            &fixture.supervisor,
            adoption_424_request(&fixture, OverwatcherAssertion::PreservedActive),
        )
        .unwrap();

    let result = fixture
        .store
        .adopt_method_contract(
            &fixture.supervisor,
            adoption_425_request(&fixture, OverwatcherAssertion::PreservedActive),
        )
        .unwrap();

    assert_eq!(result.effective_version, "4.2.5");
    let after = fixture.store.query_run("run-a").unwrap();
    assert_eq!(after.summary.slk_version, "4.2.5");
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
fn supervisor_resumes_the_same_overwatcher_session_on_a_new_turn_after_an_anomaly_pause() {
    let (fixture, overwatcher) = fixture_426_with_anomaly();
    let previous_revision = fixture.runtime_revision();
    let evidence =
        fixture.evidence_ref("resumed-turn-live.json", b"same session active on new turn");

    fixture
        .store
        .resume_overwatcher_turn(
            &fixture.supervisor,
            ResumeOverwatcherTurnRequest {
                event_id: "resume-overwatcher-turn-2".into(),
                run_id: "run-a".into(),
                role_instance_id: "overwatcher-a".into(),
                session_id: "session-overwatcher-a".into(),
                binding_revision: 1,
                expected_runtime_revision: previous_revision,
                previous_foreground_turn_id: "foreground-turn-a".into(),
                foreground_turn_id: "foreground-turn-b".into(),
                last_anomaly_cycle_id: Some("cycle-2".into()),
                last_native_status_id: None,
                native_active_session_evidence: evidence,
                reason: "Supervisor resolved the reported anomaly and woke the same Session".into(),
                occurred_at: "2026-09-23T00:08:01Z".into(),
            },
        )
        .unwrap();

    let projection = fixture.store.query_run("run-a").unwrap();
    let runtime = projection.runtime_snapshot.unwrap();
    assert_eq!(runtime.runtime_revision, previous_revision + 1);
    assert_eq!(runtime.latest_event_id, "resume-overwatcher-turn-2");
    assert_eq!(projection.summary.slk_version, "4.2.6");

    let mut resumed = overwatch_cycle(3);
    resumed.foreground_turn_id = "foreground-turn-b".into();
    resumed.runtime_revision = runtime.runtime_revision;
    resumed.latest_event_id = runtime.latest_event_id;
    resumed.latest_message_id = runtime.latest_message_id;
    resumed.started_at = "2026-09-23T00:11:59Z".into();
    resumed.completed_at = "2026-09-23T00:12:00Z".into();
    resumed.next_cycle_at = "2026-09-23T00:16:00Z".into();
    resumed.evidence_refs =
        vec![fixture.evidence_ref("cycle-resumed.json", b"resumed observation")];
    resumed.native_active_session_evidence_ref = resumed.evidence_refs[0].path.clone();
    fixture
        .store
        .record_overwatch_cycle(&overwatcher, resumed)
        .unwrap();

    let database = slk_state_core::schema::open_database(fixture._root.path()).unwrap();
    let binding_turn: String = database
        .query_row(
            "SELECT foreground_turn_id FROM overwatcher_bindings WHERE run_id='run-a'",
            [],
            |row| row.get(0),
        )
        .unwrap();
    let turns: (String, String) = database
        .query_row(
            "SELECT
                (SELECT foreground_turn_id FROM overwatch_cycles WHERE cycle_id='cycle-2'),
                (SELECT foreground_turn_id FROM overwatch_cycles WHERE cycle_id='cycle-3')",
            [],
            |row| Ok((row.get(0)?, row.get(1)?)),
        )
        .unwrap();
    assert_eq!(binding_turn, "foreground-turn-b");
    assert_eq!(
        turns,
        ("foreground-turn-a".into(), "foreground-turn-b".into())
    );
}

#[test]
fn supervisor_resumes_the_same_overwatcher_session_from_the_exact_latest_native_status() {
    for fixture in [Fixture::new_428(), Fixture::new_429(), Fixture::new_4210()] {
        let issued = fixture
            .store
            .bind_overwatcher(
                &fixture.supervisor,
                overwatcher_binding("run-a", "overwatcher-a", "session-overwatcher-a"),
            )
            .unwrap();
        fixture
            .store
            .record_overwatcher_status(
                &issued.credential,
                RecordOverwatcherStatusRequest {
                    status_id: "mismatched-native-status-a".into(),
                    run_id: "run-a".into(),
                    binding_revision: 1,
                    role_instance_id: "overwatcher-a".into(),
                    session_id: "session-overwatcher-a".into(),
                    foreground_turn_id: "foreground-turn-a".into(),
                    native_liveness: NativeLiveness::Mismatched,
                    evidence: fixture.evidence_ref("mismatched-status.json", b"mismatched"),
                    observed_at: "2026-09-24T01:00:00Z".into(),
                },
            )
            .unwrap();
        let before = fixture.store.query_run("run-a").unwrap();
        let before_runtime = before.runtime_snapshot.unwrap().runtime_revision;

        fixture
            .store
            .resume_overwatcher_turn(
                &fixture.supervisor,
                ResumeOverwatcherTurnRequest {
                    event_id: "resume-from-native-status-a".into(),
                    run_id: "run-a".into(),
                    role_instance_id: "overwatcher-a".into(),
                    session_id: "session-overwatcher-a".into(),
                    binding_revision: 1,
                    expected_runtime_revision: before_runtime,
                    previous_foreground_turn_id: "foreground-turn-a".into(),
                    foreground_turn_id: "foreground-turn-b".into(),
                    last_anomaly_cycle_id: None,
                    last_native_status_id: Some("mismatched-native-status-a".into()),
                    native_active_session_evidence: fixture
                        .evidence_ref("resumed-native-status.json", b"same session active"),
                    reason: "resume the exact same Session from its native status receipt".into(),
                    occurred_at: "2026-09-24T01:00:01Z".into(),
                },
            )
            .unwrap();

        let after = fixture.store.query_run("run-a").unwrap();
        let watcher = after.role("overwatcher").unwrap();
        assert_eq!(watcher.role_instance_id, "overwatcher-a");
        assert_eq!(watcher.session_id, "session-overwatcher-a");
        assert_eq!(after.overwatcher_binding_transitions.len(), 1);
        assert_eq!(
            after.overwatcher_incident_transitions.last().unwrap().state,
            "RESOLVED"
        );
        let runtime = after.runtime_snapshot.unwrap();
        assert_eq!(runtime.runtime_revision, before_runtime + 1);
        assert_eq!(runtime.overwatcher_status.as_deref(), Some("ACTIVE"));

        let mut resumed = overwatch_cycle(1);
        resumed.foreground_turn_id = "foreground-turn-b".into();
        resumed.runtime_revision = runtime.runtime_revision;
        resumed.latest_event_id = runtime.latest_event_id;
        resumed.latest_message_id = runtime.latest_message_id;
        resumed.started_at = "2026-09-24T01:03:59Z".into();
        resumed.completed_at = "2026-09-24T01:04:00Z".into();
        resumed.next_cycle_at = "2026-09-24T01:08:00Z".into();
        resumed.evidence_refs =
            vec![fixture.evidence_ref("cycle-after-status-resume.json", b"active")];
        resumed.native_active_session_evidence_ref = resumed.evidence_refs[0].path.clone();
        fixture
            .store
            .record_overwatch_cycle(&issued.credential, resumed)
            .unwrap();
    }
}

#[test]
fn same_binding_supports_two_independent_native_pause_resume_incidents() {
    let fixture = Fixture::new_4210();
    let issued = fixture
        .store
        .bind_overwatcher(
            &fixture.supervisor,
            overwatcher_binding("run-a", "overwatcher-a", "session-overwatcher-a"),
        )
        .unwrap();

    fixture
        .store
        .record_overwatcher_status(
            &issued.credential,
            RecordOverwatcherStatusRequest {
                status_id: "native-pause-1".into(),
                run_id: "run-a".into(),
                binding_revision: 1,
                role_instance_id: "overwatcher-a".into(),
                session_id: "session-overwatcher-a".into(),
                foreground_turn_id: "foreground-turn-a".into(),
                native_liveness: NativeLiveness::Completed,
                evidence: fixture.evidence_ref("native-pause-1.json", b"turn a completed"),
                observed_at: "2026-09-24T01:00:00Z".into(),
            },
        )
        .unwrap();
    fixture
        .store
        .resume_overwatcher_turn(
            &fixture.supervisor,
            ResumeOverwatcherTurnRequest {
                event_id: "native-resume-1".into(),
                run_id: "run-a".into(),
                role_instance_id: "overwatcher-a".into(),
                session_id: "session-overwatcher-a".into(),
                binding_revision: 1,
                expected_runtime_revision: fixture.runtime_revision(),
                previous_foreground_turn_id: "foreground-turn-a".into(),
                foreground_turn_id: "foreground-turn-b".into(),
                last_anomaly_cycle_id: None,
                last_native_status_id: Some("native-pause-1".into()),
                native_active_session_evidence: fixture
                    .evidence_ref("native-resume-1.json", b"same session turn b active"),
                reason: "resume first completed foreground turn".into(),
                occurred_at: "2026-09-24T01:00:01Z".into(),
            },
        )
        .unwrap();

    fixture
        .store
        .record_overwatcher_status(
            &issued.credential,
            RecordOverwatcherStatusRequest {
                status_id: "native-pause-2".into(),
                run_id: "run-a".into(),
                binding_revision: 1,
                role_instance_id: "overwatcher-a".into(),
                session_id: "session-overwatcher-a".into(),
                foreground_turn_id: "foreground-turn-b".into(),
                native_liveness: NativeLiveness::Completed,
                evidence: fixture.evidence_ref("native-pause-2.json", b"turn b completed"),
                observed_at: "2026-09-24T01:04:00Z".into(),
            },
        )
        .unwrap();
    fixture
        .store
        .resume_overwatcher_turn(
            &fixture.supervisor,
            ResumeOverwatcherTurnRequest {
                event_id: "native-resume-2".into(),
                run_id: "run-a".into(),
                role_instance_id: "overwatcher-a".into(),
                session_id: "session-overwatcher-a".into(),
                binding_revision: 1,
                expected_runtime_revision: fixture.runtime_revision(),
                previous_foreground_turn_id: "foreground-turn-b".into(),
                foreground_turn_id: "foreground-turn-c".into(),
                last_anomaly_cycle_id: None,
                last_native_status_id: Some("native-pause-2".into()),
                native_active_session_evidence: fixture
                    .evidence_ref("native-resume-2.json", b"same session turn c active"),
                reason: "resume second completed foreground turn".into(),
                occurred_at: "2026-09-24T01:04:01Z".into(),
            },
        )
        .unwrap();

    let projection = fixture.store.query_run("run-a").unwrap();
    assert_eq!(projection.overwatcher_incident_transitions.len(), 4);
    let incident_ids = projection
        .overwatcher_incident_transitions
        .iter()
        .map(|transition| transition.incident_id.as_str())
        .collect::<std::collections::HashSet<_>>();
    assert_eq!(incident_ids.len(), 2);
    assert!(incident_ids.contains("continuity-run-a-1-native-pause-1"));
    assert!(incident_ids.contains("continuity-run-a-1-native-pause-2"));
}

#[test]
fn adoption_429_to_4210_preserves_the_schema_v8_run() {
    let fixture = Fixture::new_429();
    let before = fixture.store.query_run("run-a").unwrap();
    let request = AdoptMethodContractRequest {
        receipt_id: "adopt-run-a-4210".into(),
        run_id: "run-a".into(),
        expected_snapshot: fixture.store.run_state_snapshot("run-a").unwrap(),
        from_version: "4.2.9".into(),
        to_version: "4.2.10".into(),
        owner_authorization: OwnerAuthorizationEvidence {
            source_thread_id: "owner-thread-4210".into(),
            message_id: "owner-message-4210".into(),
            content_sha256: "e".repeat(64),
            decision: OwnerDecision::ApproveMethodContractAdoption,
            occurred_at: "2026-09-25T00:00:00Z".into(),
        },
        reconciliation_receipt_id: None,
        compatibility: MethodCompatibilityAssertions {
            topology: PreservedAssertion::Preserved,
            role_bindings: PreservedAssertion::Preserved,
            token: PreservedAssertion::Preserved,
            engineering_history: PreservedAssertion::Preserved,
            overwatcher: OverwatcherAssertion::Absent,
        },
        reason: "adopt 4.2.10 field corrections without rewriting engineering history".into(),
        occurred_at: "2026-09-25T00:00:01Z".into(),
    };

    let applied = fixture
        .store
        .adopt_method_contract(&fixture.supervisor, request)
        .unwrap();
    let after = fixture.store.query_run("run-a").unwrap();
    assert_eq!(applied.effective_version, "4.2.10");
    assert_eq!(after.summary.slk_version, "4.2.10");
    assert_eq!(after.events, before.events);
    assert_eq!(after.token_history, before.token_history);
    assert_eq!(after.go_nodes, before.go_nodes);
}

#[test]
fn adoption_4210_to_4211_preserves_the_schema_v8_run() {
    let fixture = Fixture::new_4210();
    let before = fixture.store.query_run("run-a").unwrap();
    let request = AdoptMethodContractRequest {
        receipt_id: "adopt-run-a-4211".into(),
        run_id: "run-a".into(),
        expected_snapshot: fixture.store.run_state_snapshot("run-a").unwrap(),
        from_version: "4.2.10".into(),
        to_version: "4.2.11".into(),
        owner_authorization: OwnerAuthorizationEvidence {
            source_thread_id: "owner-thread-4211".into(),
            message_id: "owner-message-4211".into(),
            content_sha256: "f".repeat(64),
            decision: OwnerDecision::ApproveMethodContractAdoption,
            occurred_at: "2026-09-25T00:10:00Z".into(),
        },
        reconciliation_receipt_id: None,
        compatibility: MethodCompatibilityAssertions {
            topology: PreservedAssertion::Preserved,
            role_bindings: PreservedAssertion::Preserved,
            token: PreservedAssertion::Preserved,
            engineering_history: PreservedAssertion::Preserved,
            overwatcher: OverwatcherAssertion::Absent,
        },
        reason: "adopt 4.2.11 engineering-role closure without rewriting history".into(),
        occurred_at: "2026-09-25T00:10:01Z".into(),
    };

    let applied = fixture
        .store
        .adopt_method_contract(&fixture.supervisor, request)
        .unwrap();
    let after = fixture.store.query_run("run-a").unwrap();
    assert_eq!(applied.effective_version, "4.2.11");
    assert_eq!(after.summary.slk_version, "4.2.11");
    assert_eq!(after.events, before.events);
    assert_eq!(after.token_history, before.token_history);
    assert_eq!(after.go_nodes, before.go_nodes);
}

#[test]
fn adoption_4211_to_430_preserves_the_schema_v8_run() {
    let fixture = Fixture::new_4211();
    let before = fixture.store.query_run("run-a").unwrap();
    let request = AdoptMethodContractRequest {
        receipt_id: "adopt-run-a-430".into(),
        run_id: "run-a".into(),
        expected_snapshot: fixture.store.run_state_snapshot("run-a").unwrap(),
        from_version: "4.2.11".into(),
        to_version: "4.3.0".into(),
        owner_authorization: OwnerAuthorizationEvidence {
            source_thread_id: "owner-thread-430".into(),
            message_id: "owner-message-430".into(),
            content_sha256: "a".repeat(64),
            decision: OwnerDecision::ApproveMethodContractAdoption,
            occurred_at: "2026-09-28T00:10:00Z".into(),
        },
        reconciliation_receipt_id: None,
        compatibility: MethodCompatibilityAssertions {
            topology: PreservedAssertion::Preserved,
            role_bindings: PreservedAssertion::Preserved,
            token: PreservedAssertion::Preserved,
            engineering_history: PreservedAssertion::Preserved,
            overwatcher: OverwatcherAssertion::Absent,
        },
        reason: "adopt optional Temporal continuity without rewriting engineering history".into(),
        occurred_at: "2026-09-28T00:10:01Z".into(),
    };

    let applied = fixture
        .store
        .adopt_method_contract(&fixture.supervisor, request)
        .unwrap();
    let after = fixture.store.query_run("run-a").unwrap();
    assert_eq!(applied.effective_version, "4.3.0");
    assert_eq!(after.summary.slk_version, "4.3.0");
    assert_eq!(after.events, before.events);
    assert_eq!(after.token_history, before.token_history);
    assert_eq!(after.go_nodes, before.go_nodes);
}

#[test]
fn adoption_430_to_431_preserves_the_schema_v8_run() {
    let fixture = Fixture::new_4211();
    let to_430 = AdoptMethodContractRequest {
        receipt_id: "adopt-run-a-430-first".into(),
        run_id: "run-a".into(),
        expected_snapshot: fixture.store.run_state_snapshot("run-a").unwrap(),
        from_version: "4.2.11".into(),
        to_version: "4.3.0".into(),
        owner_authorization: OwnerAuthorizationEvidence {
            source_thread_id: "owner-thread-430-first".into(),
            message_id: "owner-message-430-first".into(),
            content_sha256: "a".repeat(64),
            decision: OwnerDecision::ApproveMethodContractAdoption,
            occurred_at: "2026-09-28T00:10:00Z".into(),
        },
        reconciliation_receipt_id: None,
        compatibility: MethodCompatibilityAssertions {
            topology: PreservedAssertion::Preserved,
            role_bindings: PreservedAssertion::Preserved,
            token: PreservedAssertion::Preserved,
            engineering_history: PreservedAssertion::Preserved,
            overwatcher: OverwatcherAssertion::Absent,
        },
        reason: "reach the frozen 4.3.0 contract before patch adoption".into(),
        occurred_at: "2026-09-28T00:10:01Z".into(),
    };
    fixture
        .store
        .adopt_method_contract(&fixture.supervisor, to_430)
        .unwrap();
    let before = fixture.store.query_run("run-a").unwrap();

    let to_431 = AdoptMethodContractRequest {
        receipt_id: "adopt-run-a-431".into(),
        run_id: "run-a".into(),
        expected_snapshot: fixture.store.run_state_snapshot("run-a").unwrap(),
        from_version: "4.3.0".into(),
        to_version: "4.3.1".into(),
        owner_authorization: OwnerAuthorizationEvidence {
            source_thread_id: "owner-thread-431".into(),
            message_id: "owner-message-431".into(),
            content_sha256: "b".repeat(64),
            decision: OwnerDecision::ApproveMethodContractAdoption,
            occurred_at: "2026-09-28T00:11:00Z".into(),
        },
        reconciliation_receipt_id: None,
        compatibility: MethodCompatibilityAssertions {
            topology: PreservedAssertion::Preserved,
            role_bindings: PreservedAssertion::Preserved,
            token: PreservedAssertion::Preserved,
            engineering_history: PreservedAssertion::Preserved,
            overwatcher: OverwatcherAssertion::Absent,
        },
        reason: "adopt field corrections without changing Run facts".into(),
        occurred_at: "2026-09-28T00:11:01Z".into(),
    };

    let applied = fixture
        .store
        .adopt_method_contract(&fixture.supervisor, to_431)
        .unwrap();
    let after = fixture.store.query_run("run-a").unwrap();
    assert_eq!(applied.effective_version, "4.3.1");
    assert_eq!(after.summary.slk_version, "4.3.1");
    assert_eq!(after.events, before.events);
    assert_eq!(after.token_history, before.token_history);
    assert_eq!(after.go_nodes, before.go_nodes);
}

#[test]
fn adoption_431_to_432_preserves_the_schema_v8_run() {
    let fixture = Fixture::new_4211();
    for (receipt_id, from_version, to_version, occurred_at) in [
        (
            "adopt-run-a-430-first",
            "4.2.11",
            "4.3.0",
            "2026-09-28T00:10:01Z",
        ),
        (
            "adopt-run-a-431-first",
            "4.3.0",
            "4.3.1",
            "2026-09-28T00:11:01Z",
        ),
    ] {
        let request = AdoptMethodContractRequest {
            receipt_id: receipt_id.into(),
            run_id: "run-a".into(),
            expected_snapshot: fixture.store.run_state_snapshot("run-a").unwrap(),
            from_version: from_version.into(),
            to_version: to_version.into(),
            owner_authorization: OwnerAuthorizationEvidence {
                source_thread_id: format!("owner-thread-{receipt_id}"),
                message_id: format!("owner-message-{receipt_id}"),
                content_sha256: "c".repeat(64),
                decision: OwnerDecision::ApproveMethodContractAdoption,
                occurred_at: occurred_at.into(),
            },
            reconciliation_receipt_id: None,
            compatibility: MethodCompatibilityAssertions {
                topology: PreservedAssertion::Preserved,
                role_bindings: PreservedAssertion::Preserved,
                token: PreservedAssertion::Preserved,
                engineering_history: PreservedAssertion::Preserved,
                overwatcher: OverwatcherAssertion::Absent,
            },
            reason: format!("reach {to_version} before the next patch adoption"),
            occurred_at: occurred_at.into(),
        };
        fixture
            .store
            .adopt_method_contract(&fixture.supervisor, request)
            .unwrap();
    }
    let before = fixture.store.query_run("run-a").unwrap();
    let request = AdoptMethodContractRequest {
        receipt_id: "adopt-run-a-432".into(),
        run_id: "run-a".into(),
        expected_snapshot: fixture.store.run_state_snapshot("run-a").unwrap(),
        from_version: "4.3.1".into(),
        to_version: "4.3.2".into(),
        owner_authorization: OwnerAuthorizationEvidence {
            source_thread_id: "owner-thread-432".into(),
            message_id: "owner-message-432".into(),
            content_sha256: "d".repeat(64),
            decision: OwnerDecision::ApproveMethodContractAdoption,
            occurred_at: "2026-09-29T00:10:00Z".into(),
        },
        reconciliation_receipt_id: None,
        compatibility: MethodCompatibilityAssertions {
            topology: PreservedAssertion::Preserved,
            role_bindings: PreservedAssertion::Preserved,
            token: PreservedAssertion::Preserved,
            engineering_history: PreservedAssertion::Preserved,
            overwatcher: OverwatcherAssertion::Absent,
        },
        reason: "adopt Desktop current-turn recovery without rewriting Run facts".into(),
        occurred_at: "2026-09-29T00:10:01Z".into(),
    };

    let applied = fixture
        .store
        .adopt_method_contract(&fixture.supervisor, request)
        .unwrap();
    let after = fixture.store.query_run("run-a").unwrap();
    assert_eq!(applied.effective_version, "4.3.2");
    assert_eq!(after.summary.slk_version, "4.3.2");
    assert_eq!(after.events, before.events);
    assert_eq!(after.token_history, before.token_history);
    assert_eq!(after.go_nodes, before.go_nodes);
}

#[test]
fn adoption_433_to_434_to_435_to_436_preserves_the_schema_v8_run() {
    let fixture = Fixture::new_428();
    for (receipt_id, from_version, to_version, occurred_at) in [
        ("adopt-429", "4.2.8", "4.2.9", "2026-09-24T00:09:00Z"),
        ("adopt-4210", "4.2.9", "4.2.10", "2026-09-25T00:10:00Z"),
        ("adopt-4211", "4.2.10", "4.2.11", "2026-09-26T00:11:00Z"),
        ("adopt-430", "4.2.11", "4.3.0", "2026-09-28T00:10:00Z"),
        ("adopt-431", "4.3.0", "4.3.1", "2026-09-28T00:11:00Z"),
        ("adopt-432", "4.3.1", "4.3.2", "2026-09-29T00:12:00Z"),
        ("adopt-433", "4.3.2", "4.3.3", "2026-09-30T00:10:00Z"),
    ] {
        fixture
            .store
            .adopt_method_contract(
                &fixture.supervisor,
                AdoptMethodContractRequest {
                    receipt_id: receipt_id.into(),
                    run_id: "run-a".into(),
                    expected_snapshot: fixture.store.run_state_snapshot("run-a").unwrap(),
                    from_version: from_version.into(),
                    to_version: to_version.into(),
                    owner_authorization: OwnerAuthorizationEvidence {
                        source_thread_id: format!("owner-{receipt_id}"),
                        message_id: format!("message-{receipt_id}"),
                        content_sha256: "e".repeat(64),
                        decision: OwnerDecision::ApproveMethodContractAdoption,
                        occurred_at: occurred_at.into(),
                    },
                    reconciliation_receipt_id: None,
                    compatibility: MethodCompatibilityAssertions {
                        topology: PreservedAssertion::Preserved,
                        role_bindings: PreservedAssertion::Preserved,
                        token: PreservedAssertion::Preserved,
                        engineering_history: PreservedAssertion::Preserved,
                        overwatcher: OverwatcherAssertion::Absent,
                    },
                    reason: format!("reach {to_version}"),
                    occurred_at: occurred_at.into(),
                },
            )
            .unwrap();
    }
    let before = fixture.store.query_run("run-a").unwrap();
    let applied = fixture
        .store
        .adopt_method_contract(
            &fixture.supervisor,
            AdoptMethodContractRequest {
                receipt_id: "adopt-434".into(),
                run_id: "run-a".into(),
                expected_snapshot: fixture.store.run_state_snapshot("run-a").unwrap(),
                from_version: "4.3.3".into(),
                to_version: "4.3.4".into(),
                owner_authorization: OwnerAuthorizationEvidence {
                    source_thread_id: "owner-434".into(),
                    message_id: "message-434".into(),
                    content_sha256: "f".repeat(64),
                    decision: OwnerDecision::ApproveMethodContractAdoption,
                    occurred_at: "2026-09-30T00:11:00Z".into(),
                },
                reconciliation_receipt_id: None,
                compatibility: MethodCompatibilityAssertions {
                    topology: PreservedAssertion::Preserved,
                    role_bindings: PreservedAssertion::Preserved,
                    token: PreservedAssertion::Preserved,
                    engineering_history: PreservedAssertion::Preserved,
                    overwatcher: OverwatcherAssertion::Absent,
                },
                reason: "keep readiness options closed".into(),
                occurred_at: "2026-09-30T00:11:01Z".into(),
            },
        )
        .unwrap();
    let after = fixture.store.query_run("run-a").unwrap();
    assert_eq!(applied.effective_version, "4.3.4");
    assert_eq!(after.summary.slk_version, "4.3.4");
    assert_eq!(after.events, before.events);
    assert_eq!(after.token_history, before.token_history);
    assert_eq!(after.go_nodes, before.go_nodes);

    assert!(matches!(
        fixture.store.adopt_method_contract(
            &fixture.supervisor,
            AdoptMethodContractRequest {
                receipt_id: "adopt-skip-436".into(),
                run_id: "run-a".into(),
                expected_snapshot: fixture.store.run_state_snapshot("run-a").unwrap(),
                from_version: "4.3.4".into(),
                to_version: "4.3.6".into(),
                owner_authorization: OwnerAuthorizationEvidence {
                    source_thread_id: "owner-skip-436".into(),
                    message_id: "message-skip-436".into(),
                    content_sha256: "9".repeat(64),
                    decision: OwnerDecision::ApproveMethodContractAdoption,
                    occurred_at: "2026-09-30T00:11:30Z".into(),
                },
                reconciliation_receipt_id: None,
                compatibility: MethodCompatibilityAssertions {
                    topology: PreservedAssertion::Preserved,
                    role_bindings: PreservedAssertion::Preserved,
                    token: PreservedAssertion::Preserved,
                    engineering_history: PreservedAssertion::Preserved,
                    overwatcher: OverwatcherAssertion::Absent,
                },
                reason: "direct version skip must remain forbidden".into(),
                occurred_at: "2026-09-30T00:11:30Z".into(),
            },
        ),
        Err(StateError::RunAdministrationInvalid(_))
    ));

    for (receipt_id, from_version, to_version, occurred_at) in [
        ("adopt-435", "4.3.4", "4.3.5", "2026-09-30T00:12:00Z"),
        ("adopt-436", "4.3.5", "4.3.6", "2026-10-01T00:12:00Z"),
        ("adopt-440", "4.3.6", "4.4.0", "2026-10-04T00:12:00Z"),
    ] {
        let before = fixture.store.query_run("run-a").unwrap();
        let applied = fixture
            .store
            .adopt_method_contract(
                &fixture.supervisor,
                AdoptMethodContractRequest {
                    receipt_id: receipt_id.into(),
                    run_id: "run-a".into(),
                    expected_snapshot: fixture.store.run_state_snapshot("run-a").unwrap(),
                    from_version: from_version.into(),
                    to_version: to_version.into(),
                    owner_authorization: OwnerAuthorizationEvidence {
                        source_thread_id: format!("owner-{receipt_id}"),
                        message_id: format!("message-{receipt_id}"),
                        content_sha256: "a".repeat(64),
                        decision: OwnerDecision::ApproveMethodContractAdoption,
                        occurred_at: occurred_at.into(),
                    },
                    reconciliation_receipt_id: None,
                    compatibility: MethodCompatibilityAssertions {
                        topology: PreservedAssertion::Preserved,
                        role_bindings: PreservedAssertion::Preserved,
                        token: PreservedAssertion::Preserved,
                        engineering_history: PreservedAssertion::Preserved,
                        overwatcher: OverwatcherAssertion::Absent,
                    },
                    reason: format!("adopt {to_version} without rewriting Run facts"),
                    occurred_at: occurred_at.into(),
                },
            )
            .unwrap();
        let after = fixture.store.query_run("run-a").unwrap();
        assert_eq!(applied.effective_version, to_version);
        assert_eq!(after.summary.slk_version, to_version);
        assert_eq!(after.events, before.events);
        assert_eq!(after.token_history, before.token_history);
        assert_eq!(after.go_nodes, before.go_nodes);
    }
}

#[test]
fn native_status_resume_requires_exactly_one_current_eligible_basis() {
    let fixture = Fixture::new_428();
    let issued = fixture
        .store
        .bind_overwatcher(
            &fixture.supervisor,
            overwatcher_binding("run-a", "overwatcher-a", "session-overwatcher-a"),
        )
        .unwrap();
    for (status_id, native_liveness, name, bytes, observed_at) in [
        (
            "native-status-old",
            NativeLiveness::InProgress,
            "native-status-old.json",
            b"old".as_slice(),
            "2026-09-24T01:00:00Z",
        ),
        (
            "native-status-current",
            NativeLiveness::Missing,
            "native-status-current.json",
            b"current".as_slice(),
            "2026-09-24T01:00:01Z",
        ),
    ] {
        fixture
            .store
            .record_overwatcher_status(
                &issued.credential,
                RecordOverwatcherStatusRequest {
                    status_id: status_id.into(),
                    run_id: "run-a".into(),
                    binding_revision: 1,
                    role_instance_id: "overwatcher-a".into(),
                    session_id: "session-overwatcher-a".into(),
                    foreground_turn_id: "foreground-turn-a".into(),
                    native_liveness,
                    evidence: fixture.evidence_ref(name, bytes),
                    observed_at: observed_at.into(),
                },
            )
            .unwrap();
    }
    let request = ResumeOverwatcherTurnRequest {
        event_id: "resume-native-status-invalid".into(),
        run_id: "run-a".into(),
        role_instance_id: "overwatcher-a".into(),
        session_id: "session-overwatcher-a".into(),
        binding_revision: 1,
        expected_runtime_revision: fixture.runtime_revision(),
        previous_foreground_turn_id: "foreground-turn-a".into(),
        foreground_turn_id: "foreground-turn-b".into(),
        last_anomaly_cycle_id: None,
        last_native_status_id: Some("native-status-current".into()),
        native_active_session_evidence: fixture.evidence_ref("resume-invalid.json", b"active"),
        reason: "exercise fail-closed status resume inputs".into(),
        occurred_at: "2026-09-24T01:00:02Z".into(),
    };

    for invalid in [
        ResumeOverwatcherTurnRequest {
            last_anomaly_cycle_id: Some("cycle-does-not-exist".into()),
            ..request.clone()
        },
        ResumeOverwatcherTurnRequest {
            last_native_status_id: None,
            ..request.clone()
        },
        ResumeOverwatcherTurnRequest {
            last_native_status_id: Some("native-status-old".into()),
            ..request.clone()
        },
        ResumeOverwatcherTurnRequest {
            binding_revision: 2,
            ..request.clone()
        },
        ResumeOverwatcherTurnRequest {
            role_instance_id: "different-overwatcher".into(),
            ..request.clone()
        },
        ResumeOverwatcherTurnRequest {
            session_id: "different-session".into(),
            ..request.clone()
        },
        ResumeOverwatcherTurnRequest {
            previous_foreground_turn_id: "different-turn".into(),
            ..request.clone()
        },
        ResumeOverwatcherTurnRequest {
            expected_runtime_revision: request.expected_runtime_revision - 1,
            ..request.clone()
        },
    ] {
        assert!(matches!(
            fixture
                .store
                .resume_overwatcher_turn(&fixture.supervisor, invalid),
            Err(StateError::OverwatcherCycleInvalid(_))
                | Err(StateError::RuntimeRevisionMismatch { .. })
        ));
    }
    assert!(matches!(
        fixture
            .store
            .resume_overwatcher_turn(&fixture.checker, request),
        Err(StateError::OverwatcherBindingNotAuthorized)
    ));
}

#[test]
fn native_status_resume_rejects_in_progress_status_and_a_replaced_binding() {
    let active_fixture = Fixture::new_428();
    let active_issued = active_fixture
        .store
        .bind_overwatcher(
            &active_fixture.supervisor,
            overwatcher_binding("run-a", "overwatcher-a", "session-overwatcher-a"),
        )
        .unwrap();
    active_fixture
        .store
        .record_overwatcher_status(
            &active_issued.credential,
            RecordOverwatcherStatusRequest {
                status_id: "native-status-in-progress".into(),
                run_id: "run-a".into(),
                binding_revision: 1,
                role_instance_id: "overwatcher-a".into(),
                session_id: "session-overwatcher-a".into(),
                foreground_turn_id: "foreground-turn-a".into(),
                native_liveness: NativeLiveness::InProgress,
                evidence: active_fixture.evidence_ref("in-progress.json", b"active"),
                observed_at: "2026-09-24T01:00:00Z".into(),
            },
        )
        .unwrap();
    let in_progress = native_status_resume_request(
        &active_fixture,
        "native-status-in-progress",
        "resume-in-progress-status",
    );
    assert!(matches!(
        active_fixture
            .store
            .resume_overwatcher_turn(&active_fixture.supervisor, in_progress),
        Err(StateError::OverwatcherCycleInvalid(_))
    ));

    let replaced_fixture = Fixture::new_428();
    let replaced_issued = replaced_fixture
        .store
        .bind_overwatcher(
            &replaced_fixture.supervisor,
            overwatcher_binding("run-a", "overwatcher-a", "session-overwatcher-a"),
        )
        .unwrap();
    replaced_fixture
        .store
        .record_overwatcher_status(
            &replaced_issued.credential,
            RecordOverwatcherStatusRequest {
                status_id: "native-status-before-replacement".into(),
                run_id: "run-a".into(),
                binding_revision: 1,
                role_instance_id: "overwatcher-a".into(),
                session_id: "session-overwatcher-a".into(),
                foreground_turn_id: "foreground-turn-a".into(),
                native_liveness: NativeLiveness::Completed,
                evidence: replaced_fixture.evidence_ref("completed-before-replace.json", b"done"),
                observed_at: "2026-09-24T01:00:00Z".into(),
            },
        )
        .unwrap();
    replaced_fixture
        .store
        .replace_overwatcher(
            &replaced_fixture.supervisor,
            replacement_request(
                &replaced_fixture,
                OverwatcherReplacementMode::ContinuityRecovery,
                None,
                Some(replaced_fixture.evidence_ref("replace-approved.json", b"approved")),
            ),
        )
        .unwrap();
    let replaced = native_status_resume_request(
        &replaced_fixture,
        "native-status-before-replacement",
        "resume-replaced-status",
    );
    assert!(matches!(
        replaced_fixture
            .store
            .resume_overwatcher_turn(&replaced_fixture.supervisor, replaced),
        Err(StateError::OverwatcherCycleInvalid(_))
    ));
}

#[test]
fn overwatcher_turn_resume_rejects_a_new_session_and_non_supervisor_authority() {
    let (fixture, _overwatcher) = fixture_426_with_anomaly();
    let request = ResumeOverwatcherTurnRequest {
        event_id: "resume-overwatcher-invalid".into(),
        run_id: "run-a".into(),
        role_instance_id: "overwatcher-a".into(),
        session_id: "session-overwatcher-replacement".into(),
        binding_revision: 1,
        expected_runtime_revision: fixture.runtime_revision(),
        previous_foreground_turn_id: "foreground-turn-a".into(),
        foreground_turn_id: "foreground-turn-b".into(),
        last_anomaly_cycle_id: Some("cycle-2".into()),
        last_native_status_id: None,
        native_active_session_evidence: fixture.evidence_ref("invalid-resume.json", b"invalid"),
        reason: "must not replace the bound Session".into(),
        occurred_at: "2026-09-23T00:08:01Z".into(),
    };

    assert!(matches!(
        fixture
            .store
            .resume_overwatcher_turn(&fixture.supervisor, request.clone()),
        Err(StateError::OverwatcherCycleInvalid(_))
    ));
    assert!(matches!(
        fixture.store.resume_overwatcher_turn(
            &fixture.checker,
            ResumeOverwatcherTurnRequest {
                session_id: "session-overwatcher-a".into(),
                ..request
            }
        ),
        Err(StateError::OverwatcherBindingNotAuthorized)
    ));
}

#[test]
fn a_424_cycle_cannot_clear_a_terminal_worker_completion_without_handoff() {
    let fixture = Fixture::new_423();
    let issued = fixture
        .store
        .bind_overwatcher(
            &fixture.supervisor,
            overwatcher_binding("run-a", "overwatcher-a", "session-overwatcher-a"),
        )
        .unwrap();
    let mut initial_cycle = overwatch_cycle(1);
    initial_cycle.runtime_revision = fixture.runtime_revision();
    initial_cycle.latest_event_id = fixture
        .store
        .query_run("run-a")
        .unwrap()
        .runtime_snapshot
        .unwrap()
        .latest_event_id;
    initial_cycle.evidence_refs = vec![fixture.evidence_ref("cycle-424-live.json", b"active")];
    initial_cycle.native_active_session_evidence_ref = initial_cycle.evidence_refs[0].path.clone();
    fixture
        .store
        .record_overwatch_cycle(&issued.credential, initial_cycle)
        .unwrap();
    fixture
        .store
        .adopt_method_contract(
            &fixture.supervisor,
            adoption_424_request(&fixture, OverwatcherAssertion::PreservedActive),
        )
        .unwrap();
    fixture
        .store
        .commit_delivery_start(
            &fixture.supervisor,
            fixture.delivery_start_request("checker-424", "2026-09-23T00:00:02Z"),
        )
        .unwrap();
    let mut to_worker = fixture.delivery_start_request("worker-424", "2026-09-23T00:00:03Z");
    to_worker.expected_runtime_revision = fixture.runtime_revision();
    to_worker.event_id = "transport-started-worker-424".into();
    to_worker.transport_receipt_id = "start-receipt-worker-424".into();
    to_worker.start_evidence.evidence_id = "start-evidence-worker-424".into();
    to_worker.message_id = "message-worker-424".into();
    to_worker.start_evidence.message_id = to_worker.message_id.clone();
    to_worker.token_sequence = 3;
    to_worker.from_role_instance_id = "checker-a".into();
    to_worker.to_role_instance_id = "worker-a".into();
    fixture
        .store
        .commit_delivery_start(&fixture.checker, to_worker)
        .unwrap();

    // A sealed pre-fix administrative snapshot may have lost only its message
    // pointer while the authoritative TOKEN event remains intact.
    let database = slk_state_core::schema::open_database(fixture._root.path()).unwrap();
    let previous_runtime_revision = fixture.runtime_revision();
    let historical_runtime_revision = previous_runtime_revision + 1;
    database
        .execute(
            "UPDATE runs SET current_runtime_revision=?2 WHERE run_id=?1",
            rusqlite::params!["run-a", historical_runtime_revision],
        )
        .unwrap();
    database
        .execute(
            "INSERT INTO run_runtime_snapshots
             (run_id, runtime_revision, plan_revision, token_sequence,
              token_holder_role_instance_id, latest_event_id, latest_message_id,
              method_version, overwatcher_binding_revision, overwatcher_status, committed_at)
             SELECT run_id, ?2, plan_revision, token_sequence,
                    token_holder_role_instance_id, 'historic-admin-event', NULL,
                    method_version, overwatcher_binding_revision, overwatcher_status,
                    '2026-10-05T00:00:00Z'
             FROM run_runtime_snapshots WHERE run_id=?1 AND runtime_revision=?3",
            rusqlite::params![
                "run-a",
                historical_runtime_revision,
                previous_runtime_revision
            ],
        )
        .unwrap();
    drop(database);

    let snapshot = fixture
        .store
        .query_run("run-a")
        .unwrap()
        .runtime_snapshot
        .unwrap();
    let inspection = serde_json::to_vec(&json!({
        "schema_version":"slk.worker-completion-inspection/v1",
        "status":"WORKER_COMPLETION_HANDOFF_MISSING",
        "run_id":"run-a",
        "go_id":"GO-001",
        "cell_id":"CELL-001",
        "source_message_id":"message-worker-424",
        "worker_role_instance_id":"worker-a",
        "anomaly_codes":[
            "WORKER_COMPLETION_HANDOFF_MISSING",
            "COMMUNICATION_RECOVERY_REQUIRED"
        ],
        "notification_already_sent":false
    }))
    .unwrap();
    let inspection_ref = fixture.evidence_ref("worker-completion-inspection.json", &inspection);
    let live_ref = fixture.evidence_ref("cycle-424-live-2.json", b"active");
    let mut cycle = overwatch_cycle(2);
    cycle.runtime_revision = snapshot.runtime_revision;
    cycle.token_sequence = 3;
    cycle.token_holder_role_instance_id = "worker-a".into();
    cycle.latest_event_id = snapshot.latest_event_id;
    cycle.latest_message_id = Some("message-worker-424".into());
    cycle.evidence_refs = vec![live_ref, inspection_ref];
    cycle.native_active_session_evidence_ref = cycle.evidence_refs[0].path.clone();
    cycle.started_at = "2026-09-23T00:04:01Z".into();
    cycle.completed_at = "2026-09-23T00:04:02Z".into();
    cycle.next_cycle_at = "2026-09-23T00:08:02Z".into();

    assert!(matches!(
        fixture
            .store
            .record_overwatch_cycle(&issued.credential, cycle.clone()),
        Err(StateError::OverwatcherCycleInvalid(_))
    ));
    cycle.checklist.stall_and_duplicates = OverwatchCheckResult::Anomaly;
    cycle.anomaly_codes = vec![
        OverwatchAnomalyCode::WorkerCompletionHandoffMissing,
        OverwatchAnomalyCode::CommunicationRecoveryRequired,
    ];
    let mut wrong_message = cycle.clone();
    wrong_message.latest_message_id = Some("message-from-another-delivery".into());
    assert!(matches!(
        fixture
            .store
            .record_overwatch_cycle(&issued.credential, wrong_message),
        Err(StateError::OverwatcherCycleInvalid(_))
    ));
    fixture
        .store
        .record_overwatch_cycle(&issued.credential, cycle)
        .unwrap();

    let repeated_inspection = serde_json::to_vec(&json!({
        "schema_version":"slk.worker-completion-inspection/v1",
        "status":"WORKER_COMPLETION_HANDOFF_MISSING",
        "run_id":"run-a",
        "go_id":"GO-001",
        "cell_id":"CELL-001",
        "source_message_id":"message-worker-424",
        "worker_role_instance_id":"worker-a",
        "anomaly_codes":[
            "WORKER_COMPLETION_HANDOFF_MISSING",
            "COMMUNICATION_RECOVERY_REQUIRED"
        ],
        "notification_already_sent":true
    }))
    .unwrap();
    let repeated_ref = fixture.evidence_ref(
        "worker-completion-inspection-repeat.json",
        &repeated_inspection,
    );
    let repeated_live_ref = fixture.evidence_ref("cycle-424-live-3.json", b"active");
    let snapshot = fixture
        .store
        .query_run("run-a")
        .unwrap()
        .runtime_snapshot
        .unwrap();
    let mut repeated_cycle = overwatch_cycle(3);
    repeated_cycle.runtime_revision = snapshot.runtime_revision;
    repeated_cycle.token_sequence = 3;
    repeated_cycle.token_holder_role_instance_id = "worker-a".into();
    repeated_cycle.latest_event_id = snapshot.latest_event_id;
    repeated_cycle.latest_message_id = Some("message-worker-424".into());
    repeated_cycle.evidence_refs = vec![repeated_live_ref, repeated_ref];
    repeated_cycle.native_active_session_evidence_ref =
        repeated_cycle.evidence_refs[0].path.clone();
    repeated_cycle.checklist.stall_and_duplicates = OverwatchCheckResult::Anomaly;
    repeated_cycle.anomaly_codes = vec![
        OverwatchAnomalyCode::WorkerCompletionHandoffMissing,
        OverwatchAnomalyCode::CommunicationRecoveryRequired,
    ];
    repeated_cycle.started_at = "2026-09-23T00:08:03Z".into();
    repeated_cycle.completed_at = "2026-09-23T00:08:04Z".into();
    repeated_cycle.next_cycle_at = "2026-09-23T00:12:04Z".into();
    fixture
        .store
        .record_overwatch_cycle(&issued.credential, repeated_cycle)
        .unwrap();
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
fn binding_requires_the_current_supervisor_and_an_independent_role_identity() {
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
}

#[test]
fn slk_440_allows_one_exact_overwatcher_session_to_bind_multiple_runs() {
    let fixture = Fixture::new_440();
    let mut first = overwatcher_binding("run-a", "overwatcher-a", "session-overwatcher-shared");
    first.cadence_seconds = 600;
    fixture
        .store
        .bind_overwatcher(&fixture.supervisor, first)
        .unwrap();

    let mut second = init_request("run-b", "supervisor-b");
    second.occurred_at = "2026-09-22T01:00:00Z".into();
    let second_run = fixture.store.init_run(second).unwrap();
    let database = slk_state_core::schema::open_database(fixture._root.path()).unwrap();
    database
        .execute(
            "UPDATE runs SET slk_version='4.4.0' WHERE run_id='run-b'",
            [],
        )
        .unwrap();
    drop(database);
    let mut shared = overwatcher_binding("run-b", "overwatcher-b", "session-overwatcher-shared");
    shared.cadence_seconds = 600;
    shared.native_active_session_evidence_ref = "run-b/independent-native-proof.json".into();
    fixture
        .store
        .bind_overwatcher(&second_run.supervisor_credential, shared)
        .unwrap();

    assert_eq!(
        fixture
            .store
            .query_run("run-a")
            .unwrap()
            .role("overwatcher")
            .unwrap()
            .session_id,
        "session-overwatcher-shared"
    );
    assert_eq!(
        fixture
            .store
            .query_run("run-b")
            .unwrap()
            .role("overwatcher")
            .unwrap()
            .session_id,
        "session-overwatcher-shared"
    );
}

#[test]
fn slk_440_replacement_may_join_an_exact_shared_overwatcher_session() {
    let fixture = Fixture::new_440();
    let mut original = overwatcher_binding("run-a", "overwatcher-a", "session-overwatcher-a");
    original.cadence_seconds = 600;
    let issued = fixture
        .store
        .bind_overwatcher(&fixture.supervisor, original)
        .unwrap();
    let mut cycle = overwatch_cycle(1);
    cycle.cadence_seconds = 600;
    cycle.runtime_revision = fixture.runtime_revision();
    cycle.next_cycle_at = "2026-09-22T00:14:00Z".into();
    cycle.evidence_refs = vec![fixture.evidence_ref("shared-replacement-cycle.json", b"active")];
    cycle.native_active_session_evidence_ref = cycle.evidence_refs[0].path.clone();
    fixture
        .store
        .record_overwatch_cycle(&issued.credential, cycle)
        .unwrap();

    let mut second = init_request("run-b", "supervisor-b");
    second.occurred_at = "2026-09-22T01:00:00Z".into();
    let second_run = fixture.store.init_run(second).unwrap();
    let database = slk_state_core::schema::open_database(fixture._root.path()).unwrap();
    database
        .execute(
            "UPDATE runs SET slk_version='4.4.0' WHERE run_id='run-b'",
            [],
        )
        .unwrap();
    drop(database);

    let shared_evidence = fixture.evidence_ref("run-b-live.json", b"active");
    let mut shared = overwatcher_binding("run-b", "overwatcher-shared", "session-overwatcher-b");
    shared.cadence_seconds = 600;
    shared.foreground_turn_id = "foreground-turn-b".into();
    shared.native_active_session_evidence_ref = shared_evidence.path.clone();
    shared.canonical_task_id = "session-overwatcher-b".into();
    fixture
        .store
        .bind_overwatcher(&second_run.supervisor_credential, shared)
        .unwrap();

    let mut replacement = replacement_request(
        &fixture,
        OverwatcherReplacementMode::Planned,
        Some("cycle-1"),
        None,
    );
    replacement.cadence_seconds = 600;
    assert_ne!(
        replacement.native_active_session_evidence.path,
        shared_evidence.path
    );
    let mut wrong_host = replacement.clone();
    wrong_host.endpoint.host_identity = "different-real-host".into();
    assert!(matches!(
        fixture
            .store
            .replace_overwatcher(&fixture.supervisor, wrong_host),
        Err(StateError::OverwatcherSessionReused)
    ));
    fixture
        .store
        .replace_overwatcher(&fixture.supervisor, replacement)
        .unwrap();
}

#[test]
fn owner_selected_overwatcher_luna_family_is_not_fixed_to_one_generation() {
    let fixture = Fixture::new_427();
    let mut selected = overwatcher_binding("run-a", "overwatcher-luna", "session-overwatcher-luna");
    selected.identity.model = "gpt-6-luna".into();
    fixture
        .store
        .bind_overwatcher(&fixture.supervisor, selected)
        .unwrap();

    let fixture = Fixture::new_427();
    let mut wrong_class =
        overwatcher_binding("run-a", "overwatcher-sol", "session-overwatcher-sol");
    wrong_class.identity.model = "gpt-6-sol".into();
    assert!(matches!(
        fixture
            .store
            .bind_overwatcher(&fixture.supervisor, wrong_class),
        Err(StateError::OverwatcherBindingInvalid(_))
    ));
}

#[test]
fn slk_450_binds_a_declared_supervisor_subagent_without_a_model_allowlist() {
    for (model, reasoning) in [
        ("gpt-6-luna", "high"),
        ("gpt-6.1-sol", "low"),
        ("owner-selected-efficient-model", "provider-default"),
    ] {
        let fixture = Fixture::new_450();
        let before_revision = fixture.runtime_revision();
        let mut binding = subagent_binding("run-a", "overwatcher-a", "session-overwatcher-a");
        binding.identity.model = model.into();
        binding.identity.reasoning = reasoning.into();
        fixture
            .store
            .bind_overwatcher(&fixture.supervisor, binding)
            .unwrap();
        let current = fixture.store.query_run("run-a").unwrap();
        let watcher = current.role("overwatcher").unwrap();
        assert_eq!(watcher.model, model);
        assert_eq!(watcher.reasoning, reasoning);
        assert_eq!(current.summary.slk_version, "4.5.0");
        assert_eq!(current.summary.origin_slk_version, "4.4.5");
        assert_eq!(fixture.store.current_token("run-a").unwrap().sequence, 1);
        assert_eq!(current.runtime_snapshot.unwrap().runtime_revision, before_revision + 1);
    }
}

#[test]
fn slk_450_compares_the_declared_parent_and_child_with_registered_identities() {
    let invalid_addresses = [
        json!({"session_id":"session-overwatcher-a"}),
        json!({"kind":"independent_agent", "parent":{
            "agent_runtime":"codex", "host_identity":"host-a", "session_id":"session-supervisor-a"
        }, "agent_id":"session-overwatcher-a"}),
        subagent_address("different-supervisor", "session-overwatcher-a"),
        subagent_address("session-supervisor-a", "different-child"),
        json!({"kind":"supervisor_subagent", "parent":{
            "agent_runtime":"different-runtime", "host_identity":"host-a", "session_id":"session-supervisor-a"
        }, "agent_id":"session-overwatcher-a"}),
        json!({"kind":"supervisor_subagent", "parent":{
            "agent_runtime":"codex", "host_identity":"different-host", "session_id":"session-supervisor-a"
        }, "agent_id":"session-overwatcher-a"}),
    ];
    for address in invalid_addresses {
        let fixture = Fixture::new_450();
        let mut binding = subagent_binding("run-a", "overwatcher-a", "session-overwatcher-a");
        binding.endpoint.native_address = address;
        assert!(matches!(
            fixture.store.bind_overwatcher(&fixture.supervisor, binding),
            Err(StateError::OverwatcherBindingInvalid(message)) if message.contains("registered Supervisor parent and child")
        ));
    }

    let fixture = Fixture::new_450();
    let mut child = subagent_binding("run-a", "overwatcher-a", "session-overwatcher-a");
    child.identity.agent_runtime = "native-child-runtime".into();
    child.endpoint.host_identity = "native-child-host".into();
    fixture.store.bind_overwatcher(&fixture.supervisor, child).unwrap();
}

#[test]
fn slk_451_keeps_supervisor_child_identity_and_owner_model_choice() {
    let fixture = Fixture::new_450();
    slk_state_core::schema::open_database(fixture._root.path()).unwrap()
        .execute("UPDATE runs SET slk_version='4.5.1' WHERE run_id='run-a'", []).unwrap();
    let mut binding = subagent_binding("run-a", "overwatcher-a", "session-overwatcher-a");
    binding.identity.model = "gpt-6-luna".into();
    binding.identity.reasoning = "high".into();
    let mut wrong = binding.clone();
    wrong.endpoint.native_address = subagent_address("wrong-parent", "session-overwatcher-a");
    assert!(matches!(fixture.store.bind_overwatcher(&fixture.supervisor, wrong),
        Err(StateError::OverwatcherBindingInvalid(message)) if message.contains("registered Supervisor parent and child")));
    fixture.store.bind_overwatcher(&fixture.supervisor, binding).unwrap();
    let run = fixture.store.query_run("run-a").unwrap();
    assert_eq!(run.summary.slk_version, "4.5.1");
    assert_eq!(run.role("overwatcher").unwrap().reasoning, "high");
}

#[test]
fn slk_452_preserves_subagent_ownership_and_admits_initial_dispatch() {
    let fixture = Fixture::new_450();
    slk_state_core::schema::open_database(fixture._root.path()).unwrap()
        .execute("UPDATE runs SET slk_version='4.5.2' WHERE run_id='run-a'", []).unwrap();
    let binding = subagent_binding("run-a", "overwatcher-a", "session-overwatcher-a");
    let mut wrong = binding.clone();
    wrong.endpoint.native_address = subagent_address("wrong-parent", "session-overwatcher-a");
    assert!(matches!(fixture.store.bind_overwatcher(&fixture.supervisor, wrong),
        Err(StateError::OverwatcherBindingInvalid(message)) if message.contains("registered Supervisor parent and child")));
    fixture.store.bind_overwatcher(&fixture.supervisor, binding).unwrap();
    fixture.store.commit_delivery_start(&fixture.supervisor, first_subagent_dispatch(&fixture)).unwrap();
    let projection = fixture.store.query_run("run-a").unwrap();
    assert_eq!(projection.summary.slk_version, "4.5.2");
    assert!(projection.overwatch_cycles.is_empty());
    assert_eq!(fixture.store.current_token("run-a").unwrap().owner_role_instance_id, "checker-a");
}

#[test]
fn slk_453_through_455_preserve_subagent_identity_and_reject_unpublished_456() {
    for version in ["4.5.3", "4.5.4", "4.5.5"] {
    let fixture = Fixture::new_450();
    slk_state_core::schema::open_database(fixture._root.path()).unwrap()
        .execute("UPDATE runs SET slk_version=?1 WHERE run_id='run-a'", [version]).unwrap();
    let binding = subagent_binding("run-a", "overwatcher-a", "session-overwatcher-a");
    let mut wrong = binding.clone();
    wrong.endpoint.native_address = subagent_address("wrong-parent", "session-overwatcher-a");
    assert!(matches!(fixture.store.bind_overwatcher(&fixture.supervisor, wrong),
        Err(StateError::OverwatcherBindingInvalid(message)) if message.contains("registered Supervisor parent and child")));
    fixture.store.bind_overwatcher(&fixture.supervisor, binding).unwrap();
    fixture.store.commit_delivery_start(&fixture.supervisor, first_subagent_dispatch(&fixture)).unwrap();
    let projection = fixture.store.query_run("run-a").unwrap();
    assert_eq!(projection.summary.slk_version, version);
    assert_eq!(projection.runtime_snapshot.unwrap().method_version, version);
    assert_eq!(fixture.store.current_token("run-a").unwrap().owner_role_instance_id, "checker-a");
    }

    let unpublished = Fixture::new_450();
    slk_state_core::schema::open_database(unpublished._root.path()).unwrap()
        .execute("UPDATE runs SET slk_version='4.5.6' WHERE run_id='run-a'", []).unwrap();
    assert!(matches!(unpublished.store.bind_overwatcher(&unpublished.supervisor,
        subagent_binding("run-a", "overwatcher-a", "session-overwatcher-a")),
        Err(StateError::OverwatcherBindingInvalid(message)) if message.contains("supported effective SLK contract")));
    assert_eq!(unpublished.store.query_run("run-a").unwrap().summary.slk_version, "4.5.6");
    assert_eq!(unpublished.store.current_token("run-a").unwrap().sequence, 1);
}

#[test]
fn slk_450_one_supervisor_reuses_its_child_across_runs_but_cannot_bind_a_second_child() {
    let fixture = Fixture::new_450();
    fixture.store.bind_overwatcher(&fixture.supervisor,
        subagent_binding("run-a", "overwatcher-a", "session-overwatcher-a")).unwrap();
    let second = fixture.add_450_run("run-b", "supervisor-b", "session-supervisor-a");
    fixture.store.bind_overwatcher(&second,
        subagent_binding("run-b", "overwatcher-b", "session-overwatcher-a")).unwrap();
    let third = fixture.add_450_run("run-c", "supervisor-c", "session-supervisor-a");
    assert!(matches!(fixture.store.bind_overwatcher(&third,
        subagent_binding("run-c", "overwatcher-c", "session-overwatcher-c")),
        Err(StateError::OverwatcherBindingInvalid(message)) if message.contains("one active Overwatcher")
    ));
    assert_eq!(fixture.store.query_run("run-b").unwrap().role("overwatcher").unwrap().session_id,
        "session-overwatcher-a");
}

#[test]
fn slk_450_resume_requires_positive_completed_not_missing_or_mismatched() {
    for liveness in [NativeLiveness::Missing, NativeLiveness::Mismatched] {
        let fixture = Fixture::new_450();
        let issued = fixture.store.bind_overwatcher(&fixture.supervisor,
            subagent_binding("run-a", "overwatcher-a", "session-overwatcher-a")).unwrap();
        fixture.store.record_overwatcher_status(&issued.credential, RecordOverwatcherStatusRequest {
            status_id: "unknown-old-execution".into(), run_id: "run-a".into(), binding_revision: 1,
            role_instance_id: "overwatcher-a".into(), session_id: "session-overwatcher-a".into(),
            foreground_turn_id: "foreground-turn-a".into(), native_liveness: liveness,
            evidence: fixture.evidence_ref("unknown-old-execution.json", b"unknown is not completed"),
            observed_at: "2026-09-24T01:00:00Z".into(),
        }).unwrap();
        assert!(matches!(fixture.store.resume_overwatcher_turn(&fixture.supervisor,
            native_status_resume_request(&fixture, "unknown-old-execution", "reject-unproved-resume")),
            Err(StateError::OverwatcherCycleInvalid(message)) if message.contains("COMPLETED")));
    }
}

fn exact_followup_fixture(previous_status: serde_json::Value) -> (Fixture, ResumeOverwatcherTurnRequest) {
    let (fixture,request,_)=exact_followup_fixture_with_credential(previous_status);
    (fixture,request)
}

fn exact_followup_fixture_with_credential(previous_status: serde_json::Value) -> (Fixture, ResumeOverwatcherTurnRequest, slk_state_core::auth::IssuedCredential) {
    exact_followup_fixture_at(previous_status, 0)
}

fn exact_followup_fixture_at(previous_status: serde_json::Value, age_seconds: i64) -> (Fixture, ResumeOverwatcherTurnRequest, slk_state_core::auth::IssuedCredential) {
    use time::{format_description::well_known::Rfc3339, OffsetDateTime};
    let fixture = Fixture::new_450();
    let mut binding = subagent_binding("run-a", "overwatcher-a", "/root/ow");
    binding.foreground_turn_id = "codex-subagent-spawn:call_spawn".into();
    binding.canonical_task_id = "codex-subagent-spawn-call_spawn".into();
    let issued=fixture.store.bind_overwatcher(&fixture.supervisor, binding).unwrap();
    let now = OffsetDateTime::now_utc() - time::Duration::seconds(age_seconds);
    let at = |seconds| (now - time::Duration::seconds(seconds)).format(&Rfc3339).unwrap();
    let call = |name: &str, id: &str, arguments: serde_json::Value, seconds| json!({
        "timestamp": at(seconds), "type":"response_item", "payload":{
            "type":"function_call", "namespace":"collaboration", "name":name,
            "call_id":id,"arguments":arguments.to_string()}});
    let output = |id: &str, body: String, seconds| json!({"timestamp":at(seconds),"type":"response_item",
        "payload":{"type":"function_call_output","call_id":id,"output":body}});
    let records = vec![json!({"type":"session_meta","payload":{"id":"session-supervisor-a"}}),
        call("spawn_agent","call_spawn",json!({"task_name":"ow","message":"PRIVATE"}),4),
        output("call_spawn",json!({"task_name":"/root/ow"}).to_string(),4),
        call("list_agents","call_pre",json!({}),3),
        output("call_pre",json!({"agents":[{"agent_name":"/root/ow","agent_status":previous_status}]}).to_string(),3),
        call("followup_task","call_next",json!({"target":"/root/ow","message":"PRIVATE"}),2),
        output("call_next",String::new(),2),
        call("list_agents","call_post",json!({"path_prefix":"/root/ow"}),1),
        output("call_post",json!({"agents":[{"agent_name":"/root/ow","agent_status":"running"}]}).to_string(),1)];
    let source = fixture._root.path().join("rollout-2026-10-17T01-02-03-session-supervisor-a.jsonl");
    fs::write(&source, records.iter().map(|row| row.to_string()+"\n").collect::<String>()).unwrap();
    let request = json!({"schema_version":"slk.subagent-overwatcher-request/v1","method_version":"4.5.0",
        "run_id":"run-a","role_instance_id":"overwatcher-a","endpoint_ref":"endpoint-a",
        "native_address":subagent_address("session-supervisor-a","/root/ow"),
        "native_execution_id":"codex-subagent-followup:call_next","native_source_path":source,
        "spawn_call_id":"call_spawn","previous_native_execution_id":"codex-subagent-spawn:call_spawn",
        "pre_activation_sample_call_id":"call_pre"});
    let request_ref = fixture.evidence_ref("subagent-overwatcher-request.json", request.to_string().as_bytes());
    let mut proof = request;
    proof["schema_version"] = json!("slk.subagent-overwatcher-proof/v1");
    proof["request_sha256"] = json!(request_ref.sha256);
    proof["canonical_task_id"] = json!("codex-subagent-spawn-call_spawn");
    proof["native_task_id"] = json!("codex-subagent:session-supervisor-a:call_next:/root/ow");
    proof["sample_call_id"] = json!("call_post");
    proof["agent_status"] = json!("RUNNING");
    proof["pre_activation_agent_status"] = json!(if previous_status == "interrupted" {"FAILED"} else {"COMPLETED"});
    proof["checked_at"] = json!(at(0));
    for (prefix, index) in [("spawn",1),("previous_activation",1),("pre_activation_sample",3),("activation",5),("sample",7)] {
        for (part, offset) in [("call",0),("output",1)] {
            proof[format!("{prefix}_{part}_sha256")] = json!(format!("{:x}",Sha256::digest(records[index+offset].to_string().as_bytes())));
            proof[format!("{prefix}_{}_timestamp",if part=="call" {"query"} else {"output"})] = records[index+offset]["timestamp"].clone();
        }
    }
    let start = json!({"schema_version":"slk.native-start/v2","status":"STARTED","adapter":"codex-overwatcher",
        "run_id":"run-a","cell_id":"RUN-OVERWATCH","message_id":"codex-subagent-followup-call_next",
        "request_sha256":proof["request_sha256"],"native_request_sha256":proof["activation_call_sha256"],
        "observed_at":at(0),"process":{"pid":1,"creation_time":"reader-only"},
        "native_task":{"kind":"codex-subagent","id":proof["native_task_id"],"status":"RUNNING"}});
    proof["started_sha256"] = json!(fixture.evidence_ref("started.json",start.to_string().as_bytes()).sha256);
    let evidence = fixture.evidence_ref("subagent-overwatcher-proof.json",proof.to_string().as_bytes());
    let request = ResumeOverwatcherTurnRequest {event_id:"resume-exact-followup".into(),run_id:"run-a".into(),
        role_instance_id:"overwatcher-a".into(),session_id:"/root/ow".into(),binding_revision:1,
        expected_runtime_revision:fixture.runtime_revision(),previous_foreground_turn_id:"codex-subagent-spawn:call_spawn".into(),
        foreground_turn_id:"codex-subagent-followup:call_next".into(),last_anomaly_cycle_id:None,last_native_status_id:None,
        native_active_session_evidence:evidence,reason:"reconcile exact original interrupted child followup".into(),occurred_at:at(0)};
    (fixture,request,issued)
}

#[test]
fn native_followup_retains_unknown_history_and_resolves_current_continuity_with_raw_proof() {
    let (fixture,mut request,issued)=exact_followup_fixture_with_credential(json!("interrupted"));
    fixture.store.record_overwatcher_status(&issued.credential,RecordOverwatcherStatusRequest {
        status_id:"unproved-old-observation".into(),run_id:"run-a".into(),binding_revision:1,
        role_instance_id:"overwatcher-a".into(),session_id:"/root/ow".into(),
        foreground_turn_id:request.previous_foreground_turn_id.clone(),native_liveness:NativeLiveness::Missing,
        evidence:fixture.evidence_ref("old-unknown.json",b"unproved old observation, not native failure"),
        observed_at:request.occurred_at.clone(),
    }).unwrap();
    request.expected_runtime_revision=fixture.runtime_revision();
    fixture.store.resume_overwatcher_turn(&fixture.supervisor,request).unwrap();
    let db=slk_state_core::schema::open_database(fixture._root.path()).unwrap();
    let statuses:Vec<String>=db.prepare("SELECT native_liveness FROM overwatcher_native_status_receipts").unwrap()
        .query_map([],|r| r.get(0)).unwrap().collect::<Result<_,_>>().unwrap();
    assert_eq!(statuses,vec!["MISSING"]);
    let transitions:Vec<String>=db.prepare("SELECT state FROM overwatcher_incident_transitions ORDER BY rowid").unwrap()
        .query_map([],|r| r.get(0)).unwrap().collect::<Result<_,_>>().unwrap();
    assert_eq!(transitions,vec!["OPEN","RESOLVED"]);
}

#[test]
fn native_followup_reconciles_terminal_to_running_without_fabricating_status_history() {
    for terminal in [json!("interrupted"),json!({"completed":"PRIVATE"})] {
        let (fixture,request) = exact_followup_fixture(terminal);
        let token = fixture.store.current_token("run-a").unwrap();
        fixture.store.resume_overwatcher_turn(&fixture.supervisor,request).unwrap();
        let projection = fixture.store.query_run("run-a").unwrap();
        assert_eq!(projection.role("overwatcher").unwrap().session_id,"/root/ow");
        assert_eq!(projection.role("overwatcher").unwrap().foreground_turn_id.as_deref(),Some("codex-subagent-followup:call_next"));
        assert_eq!(fixture.store.current_token("run-a").unwrap(),token);
        let database=slk_state_core::schema::open_database(fixture._root.path()).unwrap();
        assert_eq!(database.query_row("SELECT COUNT(*) FROM overwatcher_native_status_receipts",[],|r|r.get::<_,i64>(0)).unwrap(),0);
        assert_eq!(slk_state_core::schema::SCHEMA_VERSION,9);
        let details:String=database.query_row("SELECT details_json FROM work_events WHERE event_id='resume-exact-followup'",[],|r|r.get(0)).unwrap();
        assert!(details.contains("NATIVE_FOLLOWUP"));
        assert!(!details.contains("PRIVATE"));
    }
}

#[test]
fn native_followup_rejects_unproved_terminal_and_forged_identity_without_writes() {
    for damage in ["active","unknown","proof-run","proof-parent","proof-child","proof-prior","proof-new",
        "proof-terminal","missing-terminal","hash","source","missing-start","wrong-request","current-completed","later-followup",
        "latest-interrupted","latest-completed","latest-unknown","latest-wrong-namespace","pending-list","duplicate-call","duplicate-json-key","wrong-runtime","wrong-authority"] {
        let (fixture,mut request)=exact_followup_fixture(match damage {"active"=>json!("running"),"unknown"=>json!("unknown"),_=>json!("interrupted")});
        let path=std::path::Path::new(&request.native_active_session_evidence.path);
        let mut proof:serde_json::Value=serde_json::from_slice(&fs::read(path).unwrap()).unwrap();
        match damage {
            "proof-run"=>proof["run_id"]=json!("other-run"),
            "proof-parent"=>proof["native_address"]["parent"]["session_id"]=json!("other-parent"),
            "proof-child"=>proof["native_address"]["agent_id"]=json!("/root/other"),
            "proof-prior"=>proof["previous_native_execution_id"]=json!("codex-subagent-spawn:call_other"),
            "proof-new"=>proof["native_execution_id"]=json!("codex-subagent-followup:call_other"),
            "proof-terminal"=>proof["pre_activation_agent_status"]=json!("COMPLETED"),
            "missing-terminal"=>{proof.as_object_mut().unwrap().remove("pre_activation_agent_status");},
            "source"=>{fs::write(proof["native_source_path"].as_str().unwrap(),"{}\n").unwrap();},
            "missing-start"=>{fs::remove_file(path.with_file_name("started.json")).unwrap();},
            "wrong-request"=>{fs::write(path.with_file_name("subagent-overwatcher-request.json"),"{}").unwrap();},
            "current-completed"|"later-followup"|"latest-interrupted"|"latest-completed"|"latest-unknown"|"latest-wrong-namespace"|"pending-list"|"duplicate-call"|"duplicate-json-key"=>{
                let source=std::path::Path::new(proof["native_source_path"].as_str().unwrap());
                let mut rows:Vec<serde_json::Value>=fs::read_to_string(source).unwrap().lines().map(|line|serde_json::from_str(line).unwrap()).collect();
                if damage=="current-completed" {rows[8]["payload"]["output"]=json!(json!({"agents":[{"agent_name":"/root/ow","agent_status":{"completed":"private"}}]}).to_string());}
                else if damage=="later-followup" {let mut next=rows[5].clone();next["payload"]["call_id"]=json!("call_later");rows.push(next);}
                else if damage=="duplicate-call" {rows.push(rows[7].clone());}
                else if damage!="duplicate-json-key" {
                    let mut query=rows[7].clone();query["timestamp"]=json!(request.occurred_at);query["payload"]["call_id"]=json!("call_latest");
                    if damage=="latest-wrong-namespace" {query["payload"]["namespace"]=json!("unproved");}
                    rows.push(query);
                    if damage!="pending-list" {
                        let mut output=rows[8].clone();output["timestamp"]=json!(request.occurred_at);output["payload"]["call_id"]=json!("call_latest");
                        output["payload"]["output"]=json!(json!({"agents":[{"agent_name":"/root/ow","agent_status":
                            match damage {"latest-interrupted"=>json!("interrupted"),"latest-completed"=>json!({"completed":"private"}),_=>json!("unknown")}}]}).to_string());
                        rows.push(output);
                    }
                }
                let mut body=rows.iter().map(|row|row.to_string()+"\n").collect::<String>();
                if damage=="duplicate-json-key" {body=body.replacen("\"id\":\"session-supervisor-a\"","\"id\":\"other\",\"id\":\"session-supervisor-a\"",1);}
                fs::write(source,body).unwrap();
            },
            "wrong-runtime"=>request.expected_runtime_revision+=1,
            _=>{}
        }
        fs::write(path,proof.to_string()).unwrap();
        request.native_active_session_evidence.sha256=if damage=="hash" {"0".repeat(64)} else {format!("{:x}",Sha256::digest(fs::read(path).unwrap()))};
        let before=fixture.runtime_revision();
        let actor=if damage=="wrong-authority" {&fixture.checker} else {&fixture.supervisor};
        assert!(fixture.store.resume_overwatcher_turn(actor,request).is_err(),"{damage}");
        assert_eq!(fixture.runtime_revision(),before,"{damage}");
    }
}

#[test]
fn native_followup_rejects_stale_exact_raw_observation_without_writes() {
    let (fixture,request,_)=exact_followup_fixture_at(json!("interrupted"),301);
    let before=fixture.runtime_revision();
    assert!(fixture.store.resume_overwatcher_turn(&fixture.supervisor,request).is_err());
    assert_eq!(fixture.runtime_revision(),before);
}

#[test]
fn native_followup_preserves_exact_multiple_source_provenance() {
    for damage in [None,Some("metadata"),Some("location"),Some("duplicate"),Some("order"),Some("foreign-parent")] {
        let (fixture,mut resume)=exact_followup_fixture(json!("interrupted"));
        let proof_path=std::path::Path::new(&resume.native_active_session_evidence.path).to_path_buf();
        let mut proof:serde_json::Value=serde_json::from_slice(&fs::read(&proof_path).unwrap()).unwrap();
        let request_path=proof_path.with_file_name("subagent-overwatcher-request.json");
        let mut request:serde_json::Value=serde_json::from_slice(&fs::read(&request_path).unwrap()).unwrap();
        let source=std::path::PathBuf::from(proof["native_source_path"].as_str().unwrap());
        let second=source.with_file_name("explicit-second-parent-rollout.jsonl");
        let rows:Vec<serde_json::Value>=fs::read_to_string(&source).unwrap().lines().map(|line|serde_json::from_str(line).unwrap()).collect();
        fs::write(&source,rows[..7].iter().map(|r|r.to_string()+"\n").collect::<String>()).unwrap();
        let mut second_rows=vec![rows[0].clone(),rows[7].clone(),rows[8].clone()];
        if damage==Some("foreign-parent") {second_rows[0]["payload"]["id"]=json!("wrong-parent");}
        fs::write(&second,second_rows.iter().map(|r|r.to_string()+"\n").collect::<String>()).unwrap();
        request.as_object_mut().unwrap().remove("native_source_path");
        proof.as_object_mut().unwrap().remove("native_source_path");
        let paths=match damage {Some("duplicate")=>json!([source,source]),Some("order")=>json!([second,source]),_=>json!([source,second])};
        request["native_source_paths"]=paths.clone();proof["native_source_paths"]=paths;
        let location=|index:usize| json!({"path":if index<7 {&source} else {&second},
            "line":if index<7 {index+1} else {index-5},"sha256":format!("{:x}",Sha256::digest(rows[index].to_string().as_bytes()))});
        proof["source_metadata"]=json!([location(0),{"path":second,"line":1,"sha256":location(0)["sha256"]}]);
        for (prefix,index) in [("spawn",1),("previous_activation",1),("pre_activation_sample",3),("activation",5),("sample",7)] {
            proof["record_sources"][format!("{prefix}_call")]=location(index);
            proof["record_sources"][format!("{prefix}_output")]=location(index+1);
        }
        if damage==Some("metadata") {proof["source_metadata"][1]["sha256"]=json!("0".repeat(64));}
        if damage==Some("location") {proof["record_sources"]["sample_call"]["line"]=json!(3);}
        let request_ref=fixture.evidence_ref("subagent-overwatcher-request.json",request.to_string().as_bytes());
        proof["request_sha256"]=json!(request_ref.sha256);
        let mut start:serde_json::Value=serde_json::from_slice(&fs::read(proof_path.with_file_name("started.json")).unwrap()).unwrap();
        start["request_sha256"]=proof["request_sha256"].clone();
        proof["started_sha256"]=json!(fixture.evidence_ref("started.json",start.to_string().as_bytes()).sha256);
        resume.native_active_session_evidence=fixture.evidence_ref("subagent-overwatcher-proof.json",proof.to_string().as_bytes());
        let before=fixture.runtime_revision();
        let result=fixture.store.resume_overwatcher_turn(&fixture.supervisor,resume);
        assert_eq!(result.is_ok(),damage.is_none(),"{damage:?}: {result:?}");
        if damage.is_some() {assert_eq!(fixture.runtime_revision(),before);}
    }
}

#[test]
fn slk_450_anomaly_cycle_cannot_prove_the_old_execution_has_completed() {
    let (fixture, _) = fixture_426_with_anomaly();
    let database = slk_state_core::schema::open_database(fixture._root.path()).unwrap();
    database.execute("UPDATE runs SET slk_version='4.5.0' WHERE run_id='run-a'", []).unwrap();
    database.execute("UPDATE overwatcher_bindings SET native_address_json=?1 WHERE run_id='run-a'",
        [subagent_address("session-supervisor-a", "session-overwatcher-a").to_string()]).unwrap();
    let mut request = native_status_resume_request(&fixture, "unused", "reject-anomaly-resume");
    request.last_native_status_id = None;
    request.last_anomaly_cycle_id = Some("cycle-2".into());
    assert!(matches!(fixture.store.resume_overwatcher_turn(&fixture.supervisor, request),
        Err(StateError::OverwatcherCycleInvalid(message)) if message.contains("COMPLETED")));
}

#[test]
fn slk_450_current_execution_projection_tracks_each_run_without_changing_other_role_shapes() {
    let fixture = Fixture::new_450();
    let first = fixture.store.bind_overwatcher(&fixture.supervisor,
        subagent_binding("run-a", "overwatcher-a", "session-overwatcher-a")).unwrap();
    let second_supervisor = fixture.add_450_run("run-b", "supervisor-b", "session-supervisor-a");
    let second = fixture.store.bind_overwatcher(&second_supervisor,
        subagent_binding("run-b", "overwatcher-b", "session-overwatcher-a")).unwrap();
    for run_id in ["run-a", "run-b"] {
        let run = fixture.store.query_run(run_id).unwrap();
        assert_eq!(serde_json::to_value(run.role("overwatcher").unwrap()).unwrap()["foreground_turn_id"],
            "foreground-turn-a");
        assert!(serde_json::to_value(run.role("supervisor").unwrap()).unwrap().get("foreground_turn_id").is_none());
    }
    for (run_id, role_id, credential, supervisor) in [
        ("run-a", "overwatcher-a", &first.credential, &fixture.supervisor),
        ("run-b", "overwatcher-b", &second.credential, &second_supervisor),
    ] {
        fixture.store.record_overwatcher_status(credential, RecordOverwatcherStatusRequest {
            status_id: format!("completed-{run_id}"), run_id: run_id.into(), binding_revision: 1,
            role_instance_id: role_id.into(), session_id: "session-overwatcher-a".into(),
            foreground_turn_id: "foreground-turn-a".into(), native_liveness: NativeLiveness::Completed,
            evidence: fixture.evidence_ref(&format!("completed-{run_id}.json"), b"native completed"),
            observed_at: "2026-09-24T01:00:00Z".into(),
        }).unwrap();
        let mut request = native_status_resume_request(&fixture, &format!("completed-{run_id}"), &format!("resume-{run_id}"));
        request.run_id = run_id.into();
        request.role_instance_id = role_id.into();
        request.expected_runtime_revision = fixture.store.query_run(run_id).unwrap().runtime_snapshot.unwrap().runtime_revision;
        fixture.store.resume_overwatcher_turn(supervisor, request).unwrap();
        let run = fixture.store.query_run(run_id).unwrap();
        assert_eq!(serde_json::to_value(run.role("overwatcher").unwrap()).unwrap()["foreground_turn_id"],
            "foreground-turn-b");
        if run_id == "run-a" {
            assert_eq!(serde_json::to_value(fixture.store.query_run("run-b").unwrap().role("overwatcher").unwrap()).unwrap()["foreground_turn_id"],
                "foreground-turn-a");
        }
    }
}

#[test]
fn slk_450_shared_active_child_requires_consistent_identity_but_not_endpoint_version() {
    for field in ["provider", "model", "reasoning"] {
        let fixture = Fixture::new_450();
        fixture.store.bind_overwatcher(&fixture.supervisor,
            subagent_binding("run-a", "overwatcher-a", "session-overwatcher-a")).unwrap();
        let second = fixture.add_450_run("run-b", "supervisor-b", "session-supervisor-a");
        let mut conflicting = subagent_binding("run-b", "overwatcher-b", "session-overwatcher-a");
        match field {
            "provider" => conflicting.identity.provider = "different-provider".into(),
            "model" => conflicting.identity.model = "different-owner-selected-model".into(),
            "reasoning" => conflicting.identity.reasoning = "low".into(),
            _ => unreachable!(),
        }
        assert!(matches!(fixture.store.bind_overwatcher(&second, conflicting),
            Err(StateError::OverwatcherBindingInvalid(message)) if message.contains("same active Overwatcher identity")),
            "accepted conflicting {field}");
        let mut consistent = subagent_binding("run-b", "overwatcher-b", "session-overwatcher-a");
        consistent.endpoint.endpoint_version = 2;
        consistent.endpoint.native_address["caller_pipe"] = json!("run-b-transport-route");
        fixture.store.bind_overwatcher(&second, consistent).unwrap();
    }
}

#[test]
fn slk_450_rejects_another_supervisors_declared_parent() {
    let fixture = Fixture::new_450();
    fixture.store.bind_overwatcher(&fixture.supervisor,
        subagent_binding("run-a", "overwatcher-a", "session-overwatcher-a")).unwrap();
    let second = fixture.add_450_run("run-b", "supervisor-b", "session-supervisor-b");
    let shared = subagent_binding("run-b", "overwatcher-b", "session-overwatcher-a");
    assert!(matches!(fixture.store.bind_overwatcher(&second, shared),
        Err(StateError::OverwatcherBindingInvalid(_))));
}

#[test]
fn slk_450_distinct_supervisors_can_each_have_the_same_parent_scoped_child_path() {
    let fixture = Fixture::new_450();
    fixture.store.bind_overwatcher(&fixture.supervisor,
        subagent_binding("run-a", "overwatcher-a", "/root/ow")).unwrap();
    let second = fixture.add_450_run("run-b", "supervisor-b", "session-supervisor-b");
    let mut child = subagent_binding("run-b", "overwatcher-b", "/root/ow");
    child.endpoint.native_address = subagent_address("session-supervisor-b", "/root/ow");
    fixture.store.bind_overwatcher(&second, child).unwrap();
    assert_eq!(fixture.store.query_run("run-a").unwrap().role("overwatcher").unwrap().session_id,
        fixture.store.query_run("run-b").unwrap().role("overwatcher").unwrap().session_id);
}

#[test]
fn slk_450_rebind_cannot_change_the_child_parent_or_drift_the_supervisor_owner() {
    let fixture = Fixture::new_450();
    fixture.store.bind_overwatcher(&fixture.supervisor,
        subagent_binding("run-a", "overwatcher-a", "session-overwatcher-a")).unwrap();
    let mut rebound = endpoint("session-overwatcher-a");
    rebound.endpoint_version = 2;
    rebound.native_address = subagent_address("different-supervisor", "session-overwatcher-a");
    assert!(matches!(fixture.store.rebind_session(&fixture.supervisor, RebindSessionRequest {
        event_id: "wrong-subagent-parent".into(), run_id: "run-a".into(),
        role_instance_id: "overwatcher-a".into(), endpoint: rebound.clone(),
        reason: "cannot change the registered parent".into(),
        occurred_at: "2026-09-22T00:01:00Z".into(),
    }), Err(StateError::OverwatcherBindingInvalid(_))));

    assert!(matches!(fixture.store.rebind_session(&fixture.supervisor, RebindSessionRequest {
        event_id: "drift-supervisor-owner".into(), run_id: "run-a".into(),
        role_instance_id: "supervisor-a".into(), endpoint: EndpointIdentity {
            endpoint_version: 2, ..endpoint("different-supervisor")
        },
        reason: "must not detach an active child from its owner".into(),
        occurred_at: "2026-09-22T00:01:00Z".into(),
    }), Err(StateError::OverwatcherBindingInvalid(message)) if message.contains("active Overwatcher")));

    rebound.native_address = subagent_address("session-supervisor-a", "session-overwatcher-a");
    rebound.native_address["caller_pipe"] = json!("app-tools");
    fixture.store.rebind_session(&fixture.supervisor, RebindSessionRequest {
        event_id: "correct-subagent-endpoint".into(), run_id: "run-a".into(),
        role_instance_id: "overwatcher-a".into(), endpoint: rebound,
        reason: "correct transport metadata while retaining parent and child".into(),
        occurred_at: "2026-09-22T00:01:00Z".into(),
    }).unwrap();
    assert_eq!(fixture.store.query_run("run-a").unwrap().role("overwatcher").unwrap()
        .endpoints[0].endpoint_version, 2);
}

#[test]
fn slk_450_inherits_445_d2_and_run_close_protections() {
    let fixture = Fixture::new_450();
    assert!(matches!(fixture.store.write_event(&fixture.supervisor,
        event("d2-without-ready", EventType::D2Started, "supervisor-a")),
        Err(StateError::InvalidPlan(_))));
    assert!(matches!(fixture.store.write_event(&fixture.supervisor,
        event("close-without-d2", EventType::RunClosed, "supervisor-a")),
        Err(StateError::WorkEventInvalid(_))));
    assert_eq!(fixture.store.query_run("run-a").unwrap().summary.closure_state, "open");
}

#[test]
fn slk_450_replacement_validates_parent_and_does_not_split_a_shared_owner() {
    let fixture = Fixture::new_450();
    let issued = fixture.store.bind_overwatcher(&fixture.supervisor,
        subagent_binding("run-a", "overwatcher-a", "session-overwatcher-a")).unwrap();
    fixture.store.record_overwatcher_status(&issued.credential, RecordOverwatcherStatusRequest {
        status_id: "stopped-before-450-replace".into(), run_id: "run-a".into(),
        binding_revision: 1, role_instance_id: "overwatcher-a".into(),
        session_id: "session-overwatcher-a".into(), foreground_turn_id: "foreground-turn-a".into(),
        native_liveness: NativeLiveness::Completed,
        evidence: fixture.evidence_ref("stopped-450.json", b"native completed"),
        observed_at: "2026-09-22T00:05:00Z".into(),
    }).unwrap();
    let mut replacement = replacement_request(&fixture, OverwatcherReplacementMode::ContinuityRecovery,
        None, Some(fixture.evidence_ref("450-recovery-approved.json", b"approved")));
    replacement.cadence_seconds = 600;
    replacement.replacement.model = "owner-selected-efficient-model".into();
    replacement.replacement.reasoning = "low".into();
    let mut invalid = replacement.clone();
    invalid.endpoint.native_address = subagent_address("different-supervisor", "session-overwatcher-b");
    assert!(matches!(fixture.store.replace_overwatcher(&fixture.supervisor, invalid),
        Err(StateError::OverwatcherBindingInvalid(message)) if message.contains("registered Supervisor parent and child")));

    let second = fixture.add_450_run("run-b", "supervisor-b", "session-supervisor-a");
    let second_issued = fixture.store.bind_overwatcher(&second,
        subagent_binding("run-b", "overwatcher-b-other-run", "session-overwatcher-a")).unwrap();
    replacement.endpoint.native_address = subagent_address("session-supervisor-a", "session-overwatcher-b");
    assert!(matches!(fixture.store.replace_overwatcher(&fixture.supervisor, replacement),
        Err(StateError::OverwatcherBindingInvalid(message)) if message.contains("one active Overwatcher")));
    assert_eq!(fixture.store.query_run("run-a").unwrap().role("overwatcher").unwrap().session_id,
        "session-overwatcher-a");
    fixture.store.authenticate_active_role("run-b", &second_issued.credential).unwrap();
}

#[test]
fn slk_450_shared_violation_recovers_both_runs_without_reviving_the_old_child() {
    let fixture = Fixture::new_450();
    let first = fixture.store.bind_overwatcher(&fixture.supervisor,
        subagent_binding("run-a", "overwatcher-a", "session-overwatcher-a")).unwrap();
    let second_supervisor = fixture.add_450_run("run-b", "supervisor-b", "session-supervisor-a");
    let second = fixture.store.bind_overwatcher(&second_supervisor,
        subagent_binding("run-b", "overwatcher-b", "session-overwatcher-a")).unwrap();
    for (run_id, role_id, credential, status_id) in [
        ("run-a", "overwatcher-a", &first.credential, "completed-run-a"),
        ("run-b", "overwatcher-b", &second.credential, "completed-run-b"),
    ] {
        fixture.store.record_overwatcher_status(credential, RecordOverwatcherStatusRequest {
            status_id: status_id.into(), run_id: run_id.into(), binding_revision: 1,
            role_instance_id: role_id.into(), session_id: "session-overwatcher-a".into(),
            foreground_turn_id: "foreground-turn-a".into(), native_liveness: NativeLiveness::Completed,
            evidence: fixture.evidence_ref(&format!("{status_id}.json"), b"native completed"),
            observed_at: "2026-09-22T00:05:00Z".into(),
        }).unwrap();
    }
    let mut replace_first = replacement_request(&fixture, OverwatcherReplacementMode::ContinuityRecovery,
        None, Some(fixture.evidence_ref("shared-recovery-approved.json", b"approved")));
    replace_first.event_id = "recover-shared-run-a".into();
    replace_first.cadence_seconds = 600;
    replace_first.replacement = role("overwatcher-new-a", Role::Overwatcher, "session-overwatcher-new");
    replace_first.endpoint = endpoint("session-overwatcher-new");
    replace_first.endpoint.native_address = subagent_address("session-supervisor-a", "session-overwatcher-new");
    let new_first = fixture.store.replace_overwatcher(&fixture.supervisor, replace_first.clone()).unwrap();

    let old_resume = ResumeOverwatcherTurnRequest {
        event_id: "revive-old-shared-child".into(), run_id: "run-b".into(),
        role_instance_id: "overwatcher-b".into(), session_id: "session-overwatcher-a".into(),
        binding_revision: 1,
        expected_runtime_revision: fixture.store.query_run("run-b").unwrap().runtime_snapshot.unwrap().runtime_revision,
        previous_foreground_turn_id: "foreground-turn-a".into(), foreground_turn_id: "revived-old-turn".into(),
        last_anomaly_cycle_id: None, last_native_status_id: Some("completed-run-b".into()),
        native_active_session_evidence: fixture.evidence_ref("old-child-resume.json", b"claimed active"),
        reason: "must not revive a second child after recovery".into(),
        occurred_at: "2026-09-22T00:05:02Z".into(),
    };
    assert!(matches!(fixture.store.resume_overwatcher_turn(&second_supervisor, old_resume),
        Err(StateError::OverwatcherBindingInvalid(message)) if message.contains("one active Overwatcher")));
    let mut replace_second = replace_first;
    replace_second.event_id = "recover-shared-run-b".into();
    replace_second.run_id = "run-b".into();
    replace_second.replacement.role_instance_id = "overwatcher-new-b".into();
    replace_second.expected_runtime_revision = fixture.store.query_run("run-b").unwrap()
        .runtime_snapshot.unwrap().runtime_revision;
    replace_second.endpoint.endpoint_version = 2;
    let new_second = fixture.store.replace_overwatcher(&second_supervisor, replace_second).unwrap();
    for (run_id, credential) in [("run-a", &new_first.credential), ("run-b", &new_second.credential)] {
        fixture.store.authenticate_active_role(run_id, credential).unwrap();
        let run = fixture.store.query_run(run_id).unwrap();
        assert_eq!(run.role("overwatcher").unwrap().session_id, "session-overwatcher-new");
        assert_eq!(run.summary.closure_state, "open");
    }
    assert!(fixture.store.authenticate_active_role("run-a", &first.credential).is_err());
    assert!(fixture.store.authenticate_active_role("run-b", &second.credential).is_err());
}

#[test]
fn slk_450_isolated_recovery_uses_the_same_complete_model_identity_policy_as_initial_bind() {
    let fixture = Fixture::new_450();
    let issued = fixture.store.bind_overwatcher(&fixture.supervisor,
        subagent_binding("run-a", "overwatcher-a", "session-overwatcher-a")).unwrap();
    fixture.store.record_overwatcher_status(&issued.credential, RecordOverwatcherStatusRequest {
        status_id: "stopped-before-recovery".into(), run_id: "run-a".into(),
        binding_revision: 1, role_instance_id: "overwatcher-a".into(),
        session_id: "session-overwatcher-a".into(), foreground_turn_id: "foreground-turn-a".into(),
        native_liveness: NativeLiveness::Completed,
        evidence: fixture.evidence_ref("stopped-for-recovery.json", b"native completed"),
        observed_at: "2026-09-22T00:05:00Z".into(),
    }).unwrap();
    let mut replacement = replacement_request(&fixture, OverwatcherReplacementMode::ContinuityRecovery,
        None, Some(fixture.evidence_ref("recovery-approved.json", b"approved")));
    replacement.cadence_seconds = 600;
    replacement.endpoint.native_address = subagent_address("session-supervisor-a", "session-overwatcher-b");
    replacement.replacement.model = "owner-selected-efficient-model".into();
    replacement.replacement.reasoning = "low".into();
    let mut incomplete = replacement.clone();
    incomplete.replacement.session_id.clear();
    incomplete.endpoint.session_id.clear();
    incomplete.endpoint.native_address["agent_id"] = json!("");
    assert!(matches!(fixture.store.replace_overwatcher(&fixture.supervisor, incomplete),
        Err(StateError::OverwatcherBindingInvalid(_))));
    fixture.store.replace_overwatcher(&fixture.supervisor, replacement).unwrap();
    let current = fixture.store.query_run("run-a").unwrap();
    assert_eq!(current.role("overwatcher").unwrap().model, "owner-selected-efficient-model");
    assert_eq!(current.role("overwatcher").unwrap().reasoning, "low");
    assert_eq!(current.role("overwatcher").unwrap().session_id, "session-overwatcher-b");
    assert!(fixture.store.authenticate_active_role("run-a", &issued.credential).is_err());
}

#[test]
fn slk_450_closing_one_run_binding_preserves_the_other_run_and_archived_bindings_allow_rebuild() {
    let fixture = Fixture::new_450();
    let issued = fixture.store.bind_overwatcher(&fixture.supervisor,
        subagent_binding("run-a", "overwatcher-a", "session-overwatcher-a")).unwrap();
    let second = fixture.add_450_run("run-b", "supervisor-b", "session-supervisor-a");
    let second_issued = fixture.store.bind_overwatcher(&second,
        subagent_binding("run-b", "overwatcher-b", "session-overwatcher-a")).unwrap();
    fixture.store.write_event(&fixture.supervisor, WriteRequest {
        event_id: "abandon-run-a".into(), go_id: None, cell_id: None, attempt: None,
        ..event("abandon-run-a", EventType::RunAbandoned, "supervisor-a")
    }).unwrap();
    let snapshot = fixture.store.query_run("run-a").unwrap().runtime_snapshot.unwrap();
    let query = json!({"schema_version":"slk.overwatch-scope-inspection/v1", "run_id":"run-a",
        "source_message_id":null, "runtime_snapshot":snapshot, "runtime_projection_sha256":"a".repeat(64),
        "native_start_path":null, "native_start_sha256":null, "query_error":null,
        "query_started_at":"2026-09-22T00:03:59Z", "query_completed_at":"2026-09-22T00:04:00Z",
        "native_activity":{"status":"UNKNOWN", "observed_at":"2026-09-22T00:03:59Z",
            "error":"NO_NATIVE_TASK_FOR_CURRENT_TOKEN"}});
    let evidence = fixture.evidence_ref("450-final-scope.json", &serde_json::to_vec(&query).unwrap());
    let mut final_cycle = overwatch_cycle(1);
    final_cycle.go_id = None;
    final_cycle.cell_id = None;
    final_cycle.attempt = None;
    final_cycle.cadence_seconds = 600;
    final_cycle.next_cycle_at = "2026-09-22T00:14:00Z".into();
    final_cycle.runtime_revision = snapshot.runtime_revision;
    final_cycle.latest_event_id = snapshot.latest_event_id;
    final_cycle.checklist.bi_projection = OverwatchCheckResult::Anomaly;
    final_cycle.anomaly_codes = vec![OverwatchAnomalyCode::ActivityUnproven];
    final_cycle.native_active_session_evidence_ref = evidence.path.clone();
    final_cycle.evidence_refs = vec![evidence];
    fixture.store.record_overwatch_cycle(&issued.credential, final_cycle).unwrap();
    fixture.store.close_overwatcher(&issued.credential, CloseOverwatcherRequest {
        event_id: "close-only-run-a-binding".into(), run_id: "run-a".into(),
        archive_evidence_ref: "run-a-binding-archive-not-native-child-stop".into(),
        final_cycle_id: Some("cycle-1".into()), runtime_revision: Some(snapshot.runtime_revision),
        occurred_at: "2026-09-22T00:04:01Z".into(),
    }).unwrap();
    fixture.store.authenticate_active_role("run-b", &second_issued.credential).unwrap();
    assert!(fixture.store.query_run("run-b").unwrap().role("overwatcher").is_some());
    let third = fixture.add_450_run("run-c", "supervisor-c", "session-supervisor-a");
    assert!(matches!(fixture.store.bind_overwatcher(&third,
        subagent_binding("run-c", "overwatcher-c", "new-child")),
        Err(StateError::OverwatcherBindingInvalid(_))));

    // The isolated fixture models already-archived history, not a native stop.
    let archived = Fixture::new_450();
    archived.store.bind_overwatcher(&archived.supervisor,
        subagent_binding("run-a", "overwatcher-a", "session-overwatcher-a")).unwrap();
    slk_state_core::schema::open_database(archived._root.path()).unwrap().execute(
        "UPDATE overwatcher_bindings SET lifecycle_state='archived', credential_state='revoked', continuity_state='ARCHIVED'",
        [],
    ).unwrap();
    let rebuilt = archived.add_450_run("run-new", "supervisor-new", "session-supervisor-a");
    archived.store.bind_overwatcher(&rebuilt,
        subagent_binding("run-new", "overwatcher-new", "new-child")).unwrap();
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

fn first_subagent_dispatch(fixture: &Fixture) -> CommitDeliveryStartRequest {
    let mut request = fixture.delivery_start_request("before-first-cycle", "2026-09-22T00:00:03Z");
    let receipt = serde_json::to_vec(&json!({
        "schema_version": "slk.native-start/v2", "status": "STARTED", "adapter": "ocrv-checker",
        "run_id": request.run_id, "cell_id": request.cell_id, "message_id": request.message_id,
        "request_sha256": request.payload_sha256, "native_request_sha256": "a".repeat(64),
        "observed_at": request.occurred_at,
        "process": {"pid": 4321, "creation_time": "simulated-creation-time"},
        "native_task": {"kind": "ocrv-checker", "id": "simulated-checker-task", "status": "RUNNING"}
    })).unwrap();
    let evidence = fixture.evidence_ref("first-subagent-dispatch.json", &receipt);
    request.start_evidence.stored_path = evidence.path;
    request.start_evidence.sha256 = evidence.sha256;
    request
}

#[test]
fn subagent_initial_dispatch_does_not_require_a_first_observation_cycle() {
    for version in ["4.5.0", "4.5.1", "4.5.2", "4.5.3", "4.5.4"] {
        let fixture = Fixture::new_450();
        slk_state_core::schema::open_database(fixture._root.path()).unwrap()
            .execute("UPDATE runs SET slk_version=?1 WHERE run_id='run-a'", [version]).unwrap();
        fixture.store.bind_overwatcher(&fixture.supervisor,
            subagent_binding("run-a", "overwatcher-a", "session-overwatcher-a")).unwrap();
        assert!(fixture.store.query_run("run-a").unwrap().overwatch_cycles.is_empty());

        fixture.store.commit_delivery_start(&fixture.supervisor, first_subagent_dispatch(&fixture))
            .unwrap_or_else(|error| panic!("{version} blocked an active bound child before its first cycle: {error:?}"));

        let projection = fixture.store.query_run("run-a").unwrap();
        assert!(projection.overwatch_cycles.is_empty());
        assert_eq!(fixture.store.current_token("run-a").unwrap().owner_role_instance_id, "checker-a");
    }
}

#[test]
fn subagent_no_cycle_admission_preserves_bound_lifecycle_and_continuity_guards() {
    for (column, value) in [
        ("lifecycle_state", "archived"),
        ("foreground_turn_id", ""),
        ("continuity_state", "VIOLATION"),
    ] {
        let fixture = Fixture::new_450();
        fixture.store.bind_overwatcher(&fixture.supervisor,
            subagent_binding("run-a", "overwatcher-a", "session-overwatcher-a")).unwrap();
        // Corrupt only this isolated fixture to verify each pre-existing guard.
        slk_state_core::schema::open_database(fixture._root.path()).unwrap()
            .execute(&format!("UPDATE overwatcher_bindings SET {column}=?1 WHERE run_id='run-a'"), [value]).unwrap();
        assert!(matches!(fixture.store.commit_delivery_start(&fixture.supervisor, first_subagent_dispatch(&fixture)),
            Err(StateError::OverwatcherInactive(_))), "{column} guard was bypassed");
        assert_eq!(fixture.store.current_token("run-a").unwrap().sequence, 1);
    }
}

#[test]
fn legacy_revisioned_dispatch_still_requires_a_live_observation_cycle() {
    let fixture = Fixture::new_440();
    let mut binding = overwatcher_binding("run-a", "overwatcher-a", "session-overwatcher-a");
    binding.cadence_seconds = 600;
    fixture.store.bind_overwatcher(&fixture.supervisor, binding).unwrap();
    assert!(matches!(fixture.store.commit_delivery_start(&fixture.supervisor, first_subagent_dispatch(&fixture)),
        Err(StateError::OverwatcherInactive(message)) if message.contains("no complete live cycle")));
    assert_eq!(fixture.store.current_token("run-a").unwrap().sequence, 1);
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
        // Most tests in this fixture exercise the preserved 4.2.2 behavior.
        // Tests for the new contract opt in through `new_423` below.
        let database = slk_state_core::schema::open_database(root.path()).unwrap();
        database
            .execute(
                "UPDATE runs SET slk_version='4.2.2' WHERE run_id='run-a'",
                [],
            )
            .unwrap();
        drop(database);
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

    fn new_440() -> Self {
        let fixture = Self::new();
        let database = slk_state_core::schema::open_database(fixture._root.path()).unwrap();
        database
            .execute(
                "UPDATE runs SET slk_version='4.4.0' WHERE run_id='run-a'",
                [],
            )
            .unwrap();
        drop(database);
        fixture
    }

    fn new_450() -> Self {
        let fixture = Self::new();
        let database = slk_state_core::schema::open_database(fixture._root.path()).unwrap();
        // These scenarios preserve an upgraded Run's 4.4.5 origin. The
        // current_release test above covers a fresh current-product Run.
        database
            .execute(
                "UPDATE runs SET slk_version='4.5.0', origin_slk_version='4.4.5' WHERE run_id='run-a'",
                [],
            )
            .unwrap();
        fixture
    }

    fn add_450_run(&self, run_id: &str, supervisor_id: &str, supervisor_session: &str)
        -> slk_state_core::auth::Credential
    {
        let mut request = init_request(run_id, supervisor_id);
        request.supervisor.session_id = supervisor_session.into();
        request.supervisor_endpoint = endpoint(supervisor_session);
        let initialized = self.store.init_run(request).unwrap();
        slk_state_core::schema::open_database(self._root.path()).unwrap()
            .execute("UPDATE runs SET slk_version='4.5.0' WHERE run_id=?1", [run_id]).unwrap();
        initialized.supervisor_credential
    }

    fn new_427() -> Self {
        let fixture = Self::new();
        let database = slk_state_core::schema::open_database(fixture._root.path()).unwrap();
        database
            .execute(
                "UPDATE runs SET slk_version='4.2.7' WHERE run_id='run-a'",
                [],
            )
            .unwrap();
        drop(database);
        fixture
    }

    fn new_428() -> Self {
        let fixture = Self::new();
        let database = slk_state_core::schema::open_database(fixture._root.path()).unwrap();
        database
            .execute(
                "UPDATE runs SET slk_version='4.2.8' WHERE run_id='run-a'",
                [],
            )
            .unwrap();
        drop(database);
        fixture
    }

    fn new_429() -> Self {
        let fixture = Self::new();
        let database = slk_state_core::schema::open_database(fixture._root.path()).unwrap();
        database
            .execute(
                "UPDATE runs SET slk_version='4.2.9' WHERE run_id='run-a'",
                [],
            )
            .unwrap();
        drop(database);
        fixture
    }

    fn new_4210() -> Self {
        let fixture = Self::new();
        let database = slk_state_core::schema::open_database(fixture._root.path()).unwrap();
        database
            .execute(
                "UPDATE runs SET slk_version='4.2.10' WHERE run_id='run-a'",
                [],
            )
            .unwrap();
        drop(database);
        fixture
    }

    fn new_4211() -> Self {
        let fixture = Self::new();
        let database = slk_state_core::schema::open_database(fixture._root.path()).unwrap();
        database
            .execute(
                "UPDATE runs SET slk_version='4.2.11' WHERE run_id='run-a'",
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

fn credential_rotation_request(
    fixture: &Fixture,
    credential_id: &str,
) -> RotateOverwatcherCredentialRequest {
    RotateOverwatcherCredentialRequest {
        rotation_id: "rotate-overwatcher-credential-a".into(),
        run_id: "run-a".into(),
        expected_binding_revision: 1,
        expected_runtime_revision: fixture.runtime_revision(),
        role_instance_id: "overwatcher-a".into(),
        session_id: "session-overwatcher-a".into(),
        foreground_turn_id: "foreground-turn-a".into(),
        expected_overwatcher_credential_id: credential_id.into(),
        evidence: fixture.evidence_ref(
            "credential-loss.json",
            b"credential id was stored instead of secret",
        ),
        reason: "restore the exact active binding after one-time credential loss".into(),
        occurred_at: "2026-09-24T00:00:00Z".into(),
    }
}

fn native_status_resume_request(
    fixture: &Fixture,
    status_id: &str,
    event_id: &str,
) -> ResumeOverwatcherTurnRequest {
    ResumeOverwatcherTurnRequest {
        event_id: event_id.into(),
        run_id: "run-a".into(),
        role_instance_id: "overwatcher-a".into(),
        session_id: "session-overwatcher-a".into(),
        binding_revision: 1,
        expected_runtime_revision: fixture.runtime_revision(),
        previous_foreground_turn_id: "foreground-turn-a".into(),
        foreground_turn_id: "foreground-turn-b".into(),
        last_anomaly_cycle_id: None,
        last_native_status_id: Some(status_id.into()),
        native_active_session_evidence: fixture
            .evidence_ref(&format!("{event_id}.json"), b"same session active"),
        reason: "resume the exact same Session from native status evidence".into(),
        occurred_at: "2026-09-24T01:00:02Z".into(),
    }
}

fn fixture_426_with_anomaly() -> (Fixture, slk_state_core::auth::Credential) {
    let fixture = Fixture::new_423();
    let issued = fixture
        .store
        .bind_overwatcher(
            &fixture.supervisor,
            overwatcher_binding("run-a", "overwatcher-a", "session-overwatcher-a"),
        )
        .unwrap();
    let mut initial = overwatch_cycle(1);
    initial.runtime_revision = fixture.runtime_revision();
    initial.latest_event_id = fixture
        .store
        .query_run("run-a")
        .unwrap()
        .runtime_snapshot
        .unwrap()
        .latest_event_id;
    initial.evidence_refs = vec![fixture.evidence_ref("cycle-before-426.json", b"active")];
    initial.native_active_session_evidence_ref = initial.evidence_refs[0].path.clone();
    fixture
        .store
        .record_overwatch_cycle(&issued.credential, initial)
        .unwrap();
    fixture
        .store
        .adopt_method_contract(
            &fixture.supervisor,
            adoption_424_request(&fixture, OverwatcherAssertion::PreservedActive),
        )
        .unwrap();
    fixture
        .store
        .adopt_method_contract(
            &fixture.supervisor,
            adoption_425_request(&fixture, OverwatcherAssertion::PreservedActive),
        )
        .unwrap();
    fixture
        .store
        .adopt_method_contract(
            &fixture.supervisor,
            adoption_426_request(&fixture, OverwatcherAssertion::PreservedActive),
        )
        .unwrap();

    let runtime = fixture
        .store
        .query_run("run-a")
        .unwrap()
        .runtime_snapshot
        .unwrap();
    let mut anomaly = overwatch_cycle(2);
    anomaly.runtime_revision = runtime.runtime_revision;
    anomaly.latest_event_id = runtime.latest_event_id;
    anomaly.latest_message_id = runtime.latest_message_id;
    anomaly.started_at = "2026-09-23T00:07:59Z".into();
    anomaly.completed_at = "2026-09-23T00:08:00Z".into();
    anomaly.next_cycle_at = "2026-09-23T00:12:00Z".into();
    anomaly.checklist.direct_handoffs = OverwatchCheckResult::Anomaly;
    anomaly.anomaly_codes = vec![OverwatchAnomalyCode::CommunicationRecoveryRequired];
    anomaly.evidence_refs = vec![fixture.evidence_ref("cycle-anomaly.json", b"handoff missing")];
    anomaly.native_active_session_evidence_ref = anomaly.evidence_refs[0].path.clone();
    fixture
        .store
        .record_overwatch_cycle(&issued.credential, anomaly)
        .unwrap();
    (fixture, issued.credential)
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

fn adoption_424_request(
    fixture: &Fixture,
    overwatcher: OverwatcherAssertion,
) -> AdoptMethodContractRequest {
    AdoptMethodContractRequest {
        receipt_id: "adopt-run-a-424".into(),
        run_id: "run-a".into(),
        expected_snapshot: fixture.store.run_state_snapshot("run-a").unwrap(),
        from_version: "4.2.3".into(),
        to_version: "4.2.4".into(),
        owner_authorization: OwnerAuthorizationEvidence {
            source_thread_id: "owner-thread-424".into(),
            message_id: "owner-message-424".into(),
            content_sha256: "b".repeat(64),
            decision: OwnerDecision::ApproveMethodContractAdoption,
            occurred_at: "2026-09-23T00:00:00Z".into(),
        },
        reconciliation_receipt_id: None,
        compatibility: MethodCompatibilityAssertions {
            topology: PreservedAssertion::Preserved,
            role_bindings: PreservedAssertion::Preserved,
            token: PreservedAssertion::Preserved,
            engineering_history: PreservedAssertion::Preserved,
            overwatcher,
        },
        reason: "adopt the 4.2.4 Worker completion guard without changing history".into(),
        occurred_at: "2026-09-23T00:00:01Z".into(),
    }
}

fn adoption_425_request(
    fixture: &Fixture,
    overwatcher: OverwatcherAssertion,
) -> AdoptMethodContractRequest {
    AdoptMethodContractRequest {
        receipt_id: "adopt-run-a-425".into(),
        run_id: "run-a".into(),
        expected_snapshot: fixture.store.run_state_snapshot("run-a").unwrap(),
        from_version: "4.2.4".into(),
        to_version: "4.2.5".into(),
        owner_authorization: OwnerAuthorizationEvidence {
            source_thread_id: "owner-thread-425".into(),
            message_id: "owner-message-425".into(),
            content_sha256: "c".repeat(64),
            decision: OwnerDecision::ApproveMethodContractAdoption,
            occurred_at: "2026-09-23T01:00:00Z".into(),
        },
        reconciliation_receipt_id: None,
        compatibility: MethodCompatibilityAssertions {
            topology: PreservedAssertion::Preserved,
            role_bindings: PreservedAssertion::Preserved,
            token: PreservedAssertion::Preserved,
            engineering_history: PreservedAssertion::Preserved,
            overwatcher,
        },
        reason: "adopt the 4.2.5 authenticated Checker recovery boundary".into(),
        occurred_at: "2026-09-23T01:00:01Z".into(),
    }
}

fn adoption_426_request(
    fixture: &Fixture,
    overwatcher: OverwatcherAssertion,
) -> AdoptMethodContractRequest {
    AdoptMethodContractRequest {
        receipt_id: "adopt-run-a-426".into(),
        run_id: "run-a".into(),
        expected_snapshot: fixture.store.run_state_snapshot("run-a").unwrap(),
        from_version: "4.2.5".into(),
        to_version: "4.2.6".into(),
        owner_authorization: OwnerAuthorizationEvidence {
            source_thread_id: "owner-thread-426".into(),
            message_id: "owner-message-426".into(),
            content_sha256: "d".repeat(64),
            decision: OwnerDecision::ApproveMethodContractAdoption,
            occurred_at: "2026-09-23T02:00:00Z".into(),
        },
        reconciliation_receipt_id: None,
        compatibility: MethodCompatibilityAssertions {
            topology: PreservedAssertion::Preserved,
            role_bindings: PreservedAssertion::Preserved,
            token: PreservedAssertion::Preserved,
            engineering_history: PreservedAssertion::Preserved,
            overwatcher,
        },
        reason: "adopt 4.2.6 same-Session Overwatcher turn recovery without rewriting history"
            .into(),
        occurred_at: "2026-09-23T02:00:01Z".into(),
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
        canonical_task_id: format!("task-{session_id}"),
        reason: "Supervisor selected one dedicated observation Session".into(),
        occurred_at: "2026-09-22T00:00:01Z".into(),
    }
}

fn subagent_binding(
    run_id: &str,
    role_instance_id: &str,
    session_id: &str,
) -> BindOverwatcherRequest {
    let mut binding = overwatcher_binding(run_id, role_instance_id, session_id);
    binding.cadence_seconds = 600;
    binding.canonical_task_id = "native-supervisor-child".into();
    binding.endpoint.native_address = subagent_address("session-supervisor-a", session_id);
    binding
}

fn subagent_address(parent_session_id: &str, child_session_id: &str) -> serde_json::Value {
    json!({
        "kind": "supervisor_subagent",
        "parent": {
            "agent_runtime": "codex",
            "host_identity": "host-a",
            "session_id": parent_session_id,
        },
        "agent_id": child_session_id,
    })
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

#[test]
fn overwatch_cycle_attempt_must_match_current_engineering_cell() {
    let fixture = Fixture::new();
    let issued = fixture
        .store
        .bind_overwatcher(
            &fixture.supervisor,
            overwatcher_binding("run-a", "overwatcher-a", "session-overwatcher-a"),
        )
        .unwrap();
    let database = slk_state_core::schema::open_database(fixture._root.path()).unwrap();
    database
        .execute(
            "UPDATE cell_nodes SET attempt=2 WHERE run_id='run-a' AND cell_id='CELL-001'",
            [],
        )
        .unwrap();
    drop(database);
    assert!(
        matches!(fixture.store.record_overwatch_cycle(&issued.credential, overwatch_cycle(1)),
        Err(StateError::OverwatcherCycleInvalid(message)) if message.contains("attempt"))
    );
    let mut valid = overwatch_cycle(1);
    valid.attempt = Some(2);
    fixture
        .store
        .record_overwatch_cycle(&issued.credential, valid)
        .unwrap();
}

#[test]
fn current_nonworker_cycle_requires_real_query_window_but_can_report_no_task_unknown() {
    for method_version in ["4.4.3", "4.4.4", "4.4.5"] {
        nonworker_query_window_for_method(method_version);
    }
}

#[test]
fn documented_member_unknown_fragment_is_accepted_by_central_writer() {
    let fixture = Fixture::new_450();
    let issued = fixture.store.bind_overwatcher(&fixture.supervisor,
        subagent_binding("run-a", "overwatcher-a", "session-overwatcher-a")).unwrap();
    let snapshot = fixture.store.query_run("run-a").unwrap().runtime_snapshot.unwrap();
    // The independent core repository must also run this behavior test without
    // a parent SLK checkout. In the full collection additionally check doc parity.
    let fragment: serde_json::Value = serde_json::from_str(
        include_str!("fixtures/member-unknown-cycle.json")).unwrap();
    let document_path = std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("../../skills/slk-overwatch-run/references/cycle-evidence.md");
    if document_path.is_file() {
        let document = std::fs::read_to_string(document_path).unwrap().replace("\r\n", "\n");
        let documented: serde_json::Value = serde_json::from_str(
            document.split("```json\n").nth(1).unwrap().split("\n```").next().unwrap()).unwrap();
        assert_eq!(fragment, documented);
    }
    let mut value = serde_json::to_value(overwatch_cycle(1)).unwrap();
    for (key, entry) in fragment.as_object().unwrap() {
        value[key] = entry.clone();
    }
    let mut cycle: OverwatchCycleRequest = serde_json::from_value(value).unwrap();
    cycle.go_id = None;
    cycle.cell_id = None;
    cycle.attempt = None;
    cycle.runtime_revision = snapshot.runtime_revision;
    cycle.latest_event_id = snapshot.latest_event_id.clone();
    cycle.latest_message_id = snapshot.latest_message_id.clone();
    cycle.cadence_seconds = 600;
    cycle.next_cycle_at = "2026-09-22T00:14:00Z".into();
    let query = json!({"schema_version":"slk.overwatch-scope-inspection/v1", "run_id":"run-a",
        "source_message_id":null, "runtime_snapshot":snapshot, "runtime_projection_sha256":"a".repeat(64),
        "native_start_path":null, "native_start_sha256":null, "query_error":null,
        "query_started_at":cycle.started_at, "query_completed_at":cycle.completed_at,
        "native_activity":{"status":"UNKNOWN", "observed_at":cycle.completed_at,
            "error":"NO_NATIVE_TASK_FOR_CURRENT_TOKEN"}});
    let scope = fixture.evidence_ref("member-scope.json", &serde_json::to_vec(&query).unwrap());
    let own = fixture.evidence_ref("own-activation.json", b"isolated native activation fixture");
    cycle.native_active_session_evidence_ref = own.path.clone();
    cycle.evidence_refs = vec![scope, own];
    assert_eq!(cycle.native_liveness, NativeLiveness::InProgress);
    assert_eq!(cycle.checklist.active_session, OverwatchCheckResult::Clear);
    assert_eq!(cycle.checklist.stall_and_duplicates, OverwatchCheckResult::Anomaly);
    fixture.store.record_overwatch_cycle(&issued.credential, cycle).unwrap();
}

fn nonworker_query_window_for_method(method_version: &str) {
    let fixture = Fixture::new_440();
    let mut binding = overwatcher_binding("run-a", "overwatcher-a", "session-overwatcher-a");
    binding.cadence_seconds = 600;
    let issued = fixture
        .store
        .bind_overwatcher(&fixture.supervisor, binding)
        .unwrap();
    let db = slk_state_core::schema::open_database(fixture._root.path()).unwrap();
    db.execute(
        "UPDATE runs SET slk_version=?1 WHERE run_id='run-a'",
        [method_version],
    )
    .unwrap();
    drop(db);
    let snapshot = fixture
        .store
        .query_run("run-a")
        .unwrap()
        .runtime_snapshot
        .unwrap();
    let mut query = json!({"schema_version":"slk.overwatch-scope-inspection/v1", "run_id":"run-a",
        "source_message_id":null, "runtime_snapshot":snapshot, "runtime_projection_sha256":"a".repeat(64),
        "native_start_path":null, "native_start_sha256":null, "query_error":null,
        "query_started_at":"2026-09-22T00:03:00Z", "query_completed_at":"2026-09-22T00:03:01Z",
        "native_activity":{"status":"UNKNOWN", "observed_at":"2026-09-22T00:03:00Z", "error":"NO_NATIVE_TASK_FOR_CURRENT_TOKEN"}});
    let mut cycle = overwatch_cycle(1);
    cycle.go_id = None;
    cycle.cell_id = None;
    cycle.attempt = None;
    cycle.runtime_revision = snapshot.runtime_revision;
    cycle.cadence_seconds = 600;
    cycle.next_cycle_at = "2026-09-22T00:14:00Z".into();
    cycle.checklist.bi_projection = OverwatchCheckResult::Anomaly;
    cycle.anomaly_codes = vec![OverwatchAnomalyCode::ActivityUnproven];
    let old = fixture.evidence_ref("scope-query.json", &serde_json::to_vec(&query).unwrap());
    cycle.native_active_session_evidence_ref = old.path.clone();
    cycle.evidence_refs = vec![old];
    let rejected = fixture
        .store
        .record_overwatch_cycle(&issued.credential, cycle.clone());
    assert!(
        matches!(&rejected,
        Err(StateError::OverwatcherCycleInvalid(message)) if message.contains("query")),
        "{rejected:?}"
    );
    // Extending only the cycle cannot make a 17-day-old live sample current.
    let mut wide_cycle = cycle.clone();
    wide_cycle.started_at = "2026-09-05T00:03:00Z".into();
    query["query_started_at"] = json!("2026-09-05T00:03:00Z");
    query["query_completed_at"] = json!("2026-09-05T00:03:01Z");
    query["native_activity"]["observed_at"] = json!("2026-09-05T00:03:00Z");
    let stale = fixture.evidence_ref("scope-query.json", &serde_json::to_vec(&query).unwrap());
    wide_cycle.evidence_refs = vec![stale];
    let rejected = fixture
        .store
        .record_overwatch_cycle(&issued.credential, wide_cycle);
    assert!(
        matches!(&rejected,
        Err(StateError::OverwatcherCycleInvalid(message)) if message.contains("query")),
        "{rejected:?}"
    );
    query["query_started_at"] = json!("2026-09-22T00:03:59Z");
    query["query_completed_at"] = json!("2026-09-22T00:04:00Z");
    query["native_activity"]["observed_at"] = json!("2026-09-22T00:03:59.5Z");
    let fresh = fixture.evidence_ref("scope-query.json", &serde_json::to_vec(&query).unwrap());
    cycle.evidence_refs = vec![fresh];
    fixture
        .store
        .record_overwatch_cycle(&issued.credential, cycle)
        .unwrap();
}

#[test]
fn current_worker_cycle_cannot_refresh_old_completion_sample_with_a_wide_window() {
    for method_version in ["4.4.3", "4.4.4", "4.4.5"] {
        worker_query_window_for_method(method_version, false);
    }
}

#[cfg(windows)]
#[test]
fn current_cycle_accepts_same_native_file_with_windows_separator_variants_and_mixed_refs() {
    worker_query_window_for_method("4.5.4", true);
}

fn worker_query_window_for_method(method_version: &str, mixed_refs: bool) {
    let fixture = Fixture::new_423();
    let issued = fixture
        .store
        .bind_overwatcher(
            &fixture.supervisor,
            overwatcher_binding("run-a", "overwatcher-a", "session-overwatcher-a"),
        )
        .unwrap();
    let mut initial = overwatch_cycle(1);
    initial.runtime_revision = fixture.runtime_revision();
    initial.latest_event_id = fixture
        .store
        .query_run("run-a")
        .unwrap()
        .runtime_snapshot
        .unwrap()
        .latest_event_id;
    initial.evidence_refs = vec![fixture.evidence_ref("initial-worker-query.json", b"active")];
    initial.native_active_session_evidence_ref = initial.evidence_refs[0].path.clone();
    fixture
        .store
        .record_overwatch_cycle(&issued.credential, initial)
        .unwrap();
    fixture
        .store
        .commit_delivery_start(
            &fixture.supervisor,
            fixture.delivery_start_request("checker-freshness", "2026-09-22T00:00:03Z"),
        )
        .unwrap();
    let mut delivery = fixture.delivery_start_request("worker-freshness", "2026-09-22T00:00:04Z");
    delivery.token_sequence = 3;
    delivery.from_role_instance_id = "checker-a".into();
    delivery.to_role_instance_id = "worker-a".into();
    let source = EvidenceReference {
        path: delivery.start_evidence.stored_path.clone(),
        sha256: delivery.start_evidence.sha256.clone(),
    };
    fixture
        .store
        .commit_delivery_start(&fixture.checker, delivery)
        .unwrap();
    let db = slk_state_core::schema::open_database(fixture._root.path()).unwrap();
    db.execute(
        "UPDATE runs SET slk_version=?1 WHERE run_id='run-a'",
        [method_version],
    )
    .unwrap();
    db.execute(
        "UPDATE overwatcher_bindings SET cadence_seconds=600 WHERE run_id='run-a'",
        [],
    )
    .unwrap();
    drop(db);
    let snapshot = fixture
        .store
        .query_run("run-a")
        .unwrap()
        .runtime_snapshot
        .unwrap();
    let mut query = json!({"schema_version":"slk.overwatch-scope-inspection/v1", "run_id":"run-a",
        "source_message_id":snapshot.latest_message_id, "runtime_snapshot":snapshot,
        "runtime_projection_sha256":"a".repeat(64), "query_error":null,
        "native_start_path":source.path, "native_start_sha256":source.sha256,
        "query_started_at":"2026-10-09T00:03:59Z", "query_completed_at":"2026-10-09T00:04:00Z",
        "native_activity":{"status":"ACTIVE", "observed_at":"2026-10-09T00:03:59.5Z"}});
    let query_ref = fixture.evidence_ref(
        "fresh-worker-query.json",
        &serde_json::to_vec(&query).unwrap(),
    );
    let mut inspection = json!({"schema_version":"slk.worker-completion-inspection/v1",
        "status":"IN_PROGRESS", "run_id":"run-a", "go_id":"GO-001", "cell_id":"CELL-001",
        "worker_role_instance_id":"worker-a", "source_message_id":snapshot.latest_message_id,
        "observed_at":"2026-09-22T00:04:01Z", "anomaly_codes":[], "notification_already_sent":false});
    let old = fixture.evidence_ref(
        "worker-inspection.json",
        &serde_json::to_vec(&inspection).unwrap(),
    );
    let mut cycle = overwatch_cycle(2);
    cycle.started_at = "2026-09-22T00:04:01Z".into();
    cycle.completed_at = "2026-10-09T00:04:00Z".into();
    cycle.cadence_seconds = 600;
    cycle.next_cycle_at = "2026-10-09T00:14:00Z".into();
    cycle.runtime_revision = snapshot.runtime_revision;
    cycle.token_sequence = snapshot.token_sequence;
    cycle.token_holder_role_instance_id = snapshot.token_holder_role_instance_id.clone();
    cycle.latest_event_id = snapshot.latest_event_id.clone();
    cycle.latest_message_id = snapshot.latest_message_id.clone();
    cycle.native_active_session_evidence_ref = query_ref.path.clone();
    cycle.evidence_refs = vec![source, query_ref, old];
    let rejected = fixture
        .store
        .record_overwatch_cycle(&issued.credential, cycle.clone());
    assert!(
        matches!(&rejected,
        Err(StateError::OverwatcherCycleInvalid(message)) if message.contains("cadence")),
        "{rejected:?}"
    );
    inspection["observed_at"] = json!("2026-10-09T00:03:59.5Z");
    cycle.evidence_refs[2] = fixture.evidence_ref(
        "worker-inspection.json",
        &serde_json::to_vec(&inspection).unwrap(),
    );
    if mixed_refs {
        cycle.started_at="2026-10-09T00:03:59Z".into();
        cycle.next_cycle_at="2026-10-09T00:14:00+00:00".into();
        query["worker_completion"]=inspection;
        cycle.evidence_refs[1]=fixture.evidence_ref("fresh-worker-query.json",&serde_json::to_vec(&query).unwrap());
        cycle.evidence_refs.extend([
            fixture.evidence_ref("activity.json",br#"{"schema_version":"slk.native-activity/v1","status":"ACTIVE"}"#),
            fixture.evidence_ref("completion.json",br#"{"schema_version":"slk.native-completion/v1"}"#),
            fixture.evidence_ref("host.json",br#"{"schema_version":"slk.role-host/v2"}"#),
            fixture.evidence_ref("notes.txt",b"synthetic non-JSON supporting evidence"),
        ]);
        // A distinct original with identical bytes/hash must not satisfy identity.
        let mut wrong_file=cycle.clone();
        let bytes=fs::read(&cycle.evidence_refs[0].path).unwrap();
        wrong_file.evidence_refs[0]=fixture.evidence_ref("wrong-start.json",&bytes);
        assert!(fixture.store.record_overwatch_cycle(&issued.credential,wrong_file).is_err());
        // Windows separators and dot components locate the SAME original file.
        cycle.evidence_refs[0].path=cycle.evidence_refs[0].path.replace('\\',"/");
        assert_ne!(cycle.evidence_refs[0].path,query["native_start_path"].as_str().unwrap());
    }
    fixture
        .store
        .record_overwatch_cycle(&issued.credential, cycle)
        .unwrap();
}

#[test]
fn paused_idle_cycle_needs_fresh_complete_census_not_a_fabricated_native_source() {
    for method_version in ["4.4.3", "4.4.4", "4.4.5"] {
        paused_idle_census_for_method(method_version);
    }
}

fn paused_idle_census_for_method(method_version: &str) {
    let fixture = Fixture::new_440();
    let mut binding = overwatcher_binding("run-a", "overwatcher-a", "session-overwatcher-a");
    binding.cadence_seconds = 600;
    let issued = fixture
        .store
        .bind_overwatcher(&fixture.supervisor, binding)
        .unwrap();
    let db = slk_state_core::schema::open_database(fixture._root.path()).unwrap();
    db.execute(
        "UPDATE runs SET slk_version=?1 WHERE run_id='run-a'",
        [method_version],
    )
    .unwrap();
    drop(db);
    let snapshot = fixture
        .store
        .query_run("run-a")
        .unwrap()
        .runtime_snapshot
        .unwrap();
    let requested = WriteRequest {
        event_id: "pause-requested".into(),
        run_id: "run-a".into(),
        go_id: None,
        cell_id: None,
        attempt: None,
        plan_revision: 1,
        role_instance_id: "supervisor-a".into(),
        event_type: EventType::RunPauseRequested,
        details: json!({"pause_id":"pause-1","expected_runtime_revision":snapshot.runtime_revision}),
        corrects_event_id: None,
        occurred_at: "2026-09-22T00:03:57Z".into(),
    };
    fixture
        .store
        .write_event(&fixture.supervisor, requested.clone())
        .unwrap();
    let before = fixture
        .store
        .query_run("run-a")
        .unwrap()
        .runtime_snapshot
        .unwrap();
    let original = json!({"schema_version":"slk.run-quiescence/v1","run_id":"run-a","pause_id":"pause-1",
        "runtime_revision":before.runtime_revision,"status":"QUIESCENT","inspections":[],
        "attempt_roots":[fixture._root.path()],"observed_at":"2026-09-22T00:03:58Z"});
    let evidence = fixture.evidence_ref(
        "original-pause.json",
        &serde_json::to_vec(&original).unwrap(),
    );
    fixture.store.write_event(&fixture.supervisor, WriteRequest {event_id:"paused".into(), event_type:EventType::RunPaused,
        details:json!({"pause_id":"pause-1","expected_runtime_revision":before.runtime_revision,
            "quiescence_path":evidence.path,"quiescence_sha256":evidence.sha256}),
        occurred_at:"2026-09-22T00:03:58Z".into(), ..requested}).unwrap();
    let snapshot = fixture
        .store
        .query_run("run-a")
        .unwrap()
        .runtime_snapshot
        .unwrap();
    assert!(snapshot.latest_message_id.is_none());
    let query = json!({"schema_version":"slk.overwatch-scope-inspection/v1","run_id":"run-a",
        "source_message_id":null,"runtime_snapshot":snapshot,"runtime_projection_sha256":"a".repeat(64),
        "native_start_path":null,"native_start_sha256":null,"query_error":null,
        "query_started_at":"2026-09-22T00:03:59Z","query_completed_at":"2026-09-22T00:04:00Z",
        "native_activity":{"status":"UNKNOWN","observed_at":"2026-09-22T00:03:59Z","error":"NO_NATIVE_TASK_FOR_CURRENT_TOKEN"}});
    let query_ref = fixture.evidence_ref("paused-query.json", &serde_json::to_vec(&query).unwrap());
    let mut cycle = overwatch_cycle(1);
    cycle.go_id = None;
    cycle.cell_id = None;
    cycle.attempt = None;
    cycle.runtime_revision = snapshot.runtime_revision;
    cycle.latest_event_id = snapshot.latest_event_id;
    cycle.cadence_seconds = 600;
    cycle.next_cycle_at = "2026-09-22T00:14:00Z".into();
    cycle.native_active_session_evidence_ref = query_ref.path.clone();
    cycle.evidence_refs = vec![query_ref.clone()];
    assert!(fixture
        .store
        .record_overwatch_cycle(&issued.credential, cycle.clone())
        .is_err());
    let mut fresh = original;
    fresh["runtime_revision"] = json!(snapshot.runtime_revision);
    fresh["observed_at"] = json!("2026-09-22T00:03:59Z");
    fresh["status"] = json!("NOT_QUIESCENT");
    cycle
        .evidence_refs
        .push(fixture.evidence_ref("paused-fresh.json", &serde_json::to_vec(&fresh).unwrap()));
    assert!(fixture
        .store
        .record_overwatch_cycle(&issued.credential, cycle.clone())
        .is_err());
    fresh["status"] = json!("QUIESCENT");
    cycle.evidence_refs = vec![
        query_ref,
        fixture.evidence_ref("paused-fresh.json", &serde_json::to_vec(&fresh).unwrap()),
    ];
    fixture
        .store
        .record_overwatch_cycle(&issued.credential, cycle)
        .unwrap();
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

#[test]
fn creator_can_close_ended_child_without_a_fabricated_final_cycle() {
    use time::{format_description::well_known::Rfc3339, OffsetDateTime};
    for status in [json!("interrupted"), json!({"completed":"PRIVATE"}), json!("running"), json!("unknown")] {
        let (fixture, resumed) = exact_followup_fixture(json!("interrupted"));
        fixture.store.resume_overwatcher_turn(&fixture.supervisor, resumed.clone()).unwrap();
        let other = fixture.add_450_run("run-b", "supervisor-b", "session-supervisor-a");
        fixture.store.bind_overwatcher(&other, subagent_binding("run-b", "overwatcher-b", "/root/ow")).unwrap();
        let other_before = fixture.store.query_run("run-b").unwrap();
        // Engineering D2 is arranged independently of lifecycle proof in this
        // isolated fixture; closure must still check the bound D2 scope.
        let db = slk_state_core::schema::open_database(fixture._root.path()).unwrap();
        db.execute("INSERT INTO work_events (event_id,run_id,plan_revision,author_role_instance_id,event_type,details_json,occurred_at)
            VALUES ('close-d2-ready','run-a',1,'supervisor-a','D2_PASSED','{}',?1)", [&resumed.occurred_at]).unwrap();
        db.execute("INSERT INTO run_runtime_snapshots
            SELECT run_id,runtime_revision+1,plan_revision,token_sequence,token_holder_role_instance_id,'close-d2-ready',
                latest_message_id,method_version,overwatcher_binding_revision,overwatcher_status,committed_at
            FROM run_runtime_snapshots WHERE run_id='run-a' ORDER BY runtime_revision DESC LIMIT 1", []).unwrap();
        db.execute("UPDATE runs SET current_runtime_revision=current_runtime_revision+1 WHERE run_id='run-a'", []).unwrap();
        let proof: serde_json::Value = serde_json::from_slice(&fs::read(&resumed.native_active_session_evidence.path).unwrap()).unwrap();
        let source = std::path::Path::new(proof["native_source_path"].as_str().unwrap());
        let at = OffsetDateTime::now_utc().format(&Rfc3339).unwrap();
        let mut raw = fs::read_to_string(source).unwrap();
        for row in [json!({"timestamp":at,"type":"response_item","payload":{"type":"function_call",
                "namespace":"collaboration","name":"list_agents","call_id":"call_closed","arguments":"{\"path_prefix\":\"/root/ow\"}"}}),
            json!({"timestamp":at,"type":"response_item","payload":{"type":"function_call_output","call_id":"call_closed",
                "output":json!({"agents":[{"agent_name":"/root/ow","agent_status":status}]}).to_string()}})] {
            raw.push_str(&(row.to_string()+"\n"));
        }
        fs::write(source, raw).unwrap();
        let request = CloseOverwatcherRequest { event_id:"close-ended-child".into(), run_id:"run-a".into(),
            archive_evidence_ref:resumed.native_active_session_evidence.path.clone(), final_cycle_id:None,
            runtime_revision:Some(fixture.runtime_revision()), occurred_at:OffsetDateTime::now_utc().format(&Rfc3339).unwrap() };
        let before = fixture.runtime_revision();
        assert!(fixture.store.close_overwatcher(&fixture.checker, request.clone()).is_err());
        let result = fixture.store.close_overwatcher(&fixture.supervisor, request);
        let stopped = status == "interrupted" || status.is_object();
        assert_eq!(result.is_ok(), stopped, "{status}: {result:?}");
        assert_eq!(fixture.store.query_run("run-b").unwrap(), other_before);
        assert!(fixture.store.query_run("run-a").unwrap().overwatch_cycles.is_empty());
        if stopped {
            let details: String = db.query_row("SELECT details_json FROM operational_observations WHERE observation_id='close-ended-child'", [], |r| r.get(0)).unwrap();
            let value: serde_json::Value = serde_json::from_str(&details).unwrap();
            assert_eq!(value["native_exit"]["agent_status"], if status == "interrupted" { "FAILED" } else { "COMPLETED" });
            assert!(!details.contains("PRIVATE"));
        } else { assert_eq!(fixture.runtime_revision(), before); }
    }
}
