use std::fs;

use serde_json::json;
use sha2::{Digest, Sha256};

use slk_state_core::auth::StateError;
use slk_state_core::model::{
    CellDefinition, CommitDeliveryStartRequest, DeliveryStartEvidence, EndpointIdentity, EventType,
    GoDefinition, InitRunRequest, NativeStartStatus, ProjectIdentity, RegisterRoleRequest, Role,
    RoleIdentity, TokenHandoffRequest, WriteRequest,
};
use slk_state_core::write::StateStore;

#[test]
fn delivery_start_commits_receipt_token_event_and_snapshot_atomically() {
    let fixture = Fixture::new_423();
    let evidence_path = fixture.root.path().join("started.json");
    fs::write(&evidence_path, br#"{"status":"started"}"#).unwrap();
    let before_revision = fixture.runtime_revision();
    let request = start_request(&evidence_path, before_revision);

    let result = fixture
        .store
        .commit_delivery_start(&fixture.supervisor, request.clone())
        .unwrap();
    assert_eq!(result.runtime_revision, before_revision + 1);
    assert_eq!(result.token.sequence, 2);
    assert_eq!(result.token.owner_role_instance_id, "checker-a");

    let projection = fixture.store.query_run("run-a").unwrap();
    let snapshot = projection.runtime_snapshot.unwrap();
    assert_eq!(snapshot.runtime_revision, before_revision + 1);
    assert_eq!(snapshot.token_sequence, 2);
    assert_eq!(snapshot.latest_event_id, "transport-started-2");
    assert_eq!(snapshot.latest_message_id.as_deref(), Some("message-2"));
    assert_eq!(snapshot.method_version, "4.2.3");
    assert!(projection
        .events
        .iter()
        .any(|event| event.event_type == "TRANSPORT_STARTED"));

    let replay = fixture
        .store
        .commit_delivery_start(&fixture.supervisor, request)
        .unwrap();
    assert_eq!(replay.status, "IDEMPOTENT_REPLAY");
    assert_eq!(replay.runtime_revision, result.runtime_revision);
    assert_eq!(replay.token, result.token);
}

#[test]
fn invalid_start_evidence_rolls_back_every_runtime_fact() {
    let fixture = Fixture::new_423();
    let evidence_path = fixture.root.path().join("started.json");
    fs::write(&evidence_path, br#"{"status":"started"}"#).unwrap();
    let before_revision = fixture.runtime_revision();
    let mut request = start_request(&evidence_path, before_revision);
    request.start_evidence.sha256 = "0".repeat(64);

    assert!(matches!(
        fixture
            .store
            .commit_delivery_start(&fixture.supervisor, request),
        Err(StateError::EvidenceInvalid(_))
    ));
    let projection = fixture.store.query_run("run-a").unwrap();
    assert_eq!(
        projection.runtime_snapshot.unwrap().runtime_revision,
        before_revision
    );
    assert_eq!(projection.token_history.len(), 1);
    assert_eq!(projection.events.len(), 3); // init plus two role registrations
}

#[test]
fn slk_435_and_436_reject_legacy_started_marker_and_accept_exact_native_v2() {
    for method_version in ["4.3.5", "4.3.6"] {
        let fixture = Fixture::new_423();
        let connection = slk_state_core::schema::open_database(fixture.root.path()).unwrap();
        connection
            .execute(
                "UPDATE runs SET slk_version=?1 WHERE run_id='run-a'",
                [method_version],
            )
            .unwrap();
        drop(connection);
        let evidence_path = fixture.root.path().join("started.json");
        fs::write(&evidence_path, br#"{"status":"started"}"#).unwrap();
        let before_revision = fixture.runtime_revision();

        assert!(matches!(
            fixture.store.commit_delivery_start(
                &fixture.supervisor,
                start_request(&evidence_path, before_revision)
            ),
            Err(StateError::EvidenceInvalid(_))
        ));
        assert_eq!(fixture.runtime_revision(), before_revision);
        assert_eq!(fixture.store.current_token("run-a").unwrap().sequence, 1);

        fs::write(
            &evidence_path,
            serde_json::to_vec(&json!({
                "schema_version": "slk.native-start/v2",
                "status": "STARTED",
                "adapter": "ocrv-checker",
                "run_id": "run-a",
                "cell_id": "CELL-001",
                "message_id": "message-2",
                "request_sha256": "b".repeat(64),
                "native_request_sha256": "e".repeat(64),
                "observed_at": "2026-09-22T00:00:02Z",
                "process": {"pid": 4321, "creation_time": "win-filetime:12345"},
                "native_task": {"kind": "ocrv-session", "id": "ocrv-task-1", "status": "RUNNING"}
            }))
            .unwrap(),
        )
        .unwrap();
        let result = fixture
            .store
            .commit_delivery_start(
                &fixture.supervisor,
                start_request(&evidence_path, before_revision),
            )
            .unwrap();
        assert_eq!(result.token.sequence, 2);
    }
}

#[test]
fn stale_revision_and_direct_423_handoff_fail_closed() {
    let fixture = Fixture::new_423();
    let evidence_path = fixture.root.path().join("started.json");
    fs::write(&evidence_path, br#"{"status":"started"}"#).unwrap();
    let mut stale = start_request(&evidence_path, fixture.runtime_revision());
    stale.expected_runtime_revision = 9;
    assert!(matches!(
        fixture
            .store
            .commit_delivery_start(&fixture.supervisor, stale),
        Err(StateError::RuntimeRevisionMismatch { .. })
    ));

    assert!(matches!(
        fixture.store.handoff_token(
            &fixture.supervisor,
            TokenHandoffRequest {
                event_id: "legacy-token-2".into(),
                message_id: "legacy-message-2".into(),
                run_id: "run-a".into(),
                go_id: "GO-001".into(),
                cell_id: "CELL-001".into(),
                token_sequence: 2,
                from_role_instance_id: "supervisor-a".into(),
                to_role_instance_id: "checker-a".into(),
                endpoint_version: 1,
                payload_type: "CELL_ASSIGNMENT".into(),
                payload_sha256: "a".repeat(64),
                payload_location: None,
                occurred_at: "2026-09-22T00:00:02Z".into(),
            }
        ),
        Err(StateError::LegacyHandoffForbidden)
    ));
}

#[test]
fn exact_worker_event_replay_is_idempotent_only_after_424_adoption() {
    let fixture = Fixture::new_423();
    let connection = slk_state_core::schema::open_database(fixture.root.path()).unwrap();
    connection
        .execute(
            "UPDATE runs SET slk_version='4.2.4' WHERE run_id='run-a'",
            [],
        )
        .unwrap();
    connection
        .execute(
            "INSERT INTO token_events
             (event_id, run_id, token_sequence, from_role_instance_id,
              to_role_instance_id, go_id, cell_id, message_id, endpoint_version,
              event_type, payload_type, payload_sha256, payload_location, occurred_at)
             VALUES ('token-worker-2','run-a',2,'supervisor-a','worker-a','GO-001',
                     'CELL-001','message-worker-2',1,'TOKEN_HANDED_OFF',
                     'CELL_ASSIGNMENT',?1,NULL,'2026-09-22T00:00:02Z')",
            ["a".repeat(64)],
        )
        .unwrap();
    let request = WriteRequest {
        event_id: "worker-started-424".into(),
        run_id: "run-a".into(),
        go_id: Some("GO-001".into()),
        cell_id: Some("CELL-001".into()),
        attempt: Some(1),
        plan_revision: 1,
        role_instance_id: "worker-a".into(),
        event_type: EventType::WorkStarted,
        details: json!({"source_message_id":"message-worker-2"}),
        corrects_event_id: None,
        occurred_at: "2026-09-22T00:00:03Z".into(),
    };

    fixture
        .store
        .write_event(&fixture.worker, request.clone())
        .unwrap();
    connection
        .execute(
            "INSERT INTO token_events
             (event_id, run_id, token_sequence, from_role_instance_id,
              to_role_instance_id, go_id, cell_id, message_id, endpoint_version,
              event_type, payload_type, payload_sha256, payload_location, occurred_at)
             VALUES ('token-checker-3','run-a',3,'worker-a','checker-a','GO-001',
                     'CELL-001','message-checker-3',1,'TOKEN_HANDED_OFF',
                     'CANDIDATE_READY',?1,NULL,'2026-09-22T00:00:04Z')",
            ["b".repeat(64)],
        )
        .unwrap();
    fixture
        .store
        .write_event(&fixture.worker, request.clone())
        .unwrap();
    let mut conflict = request;
    conflict.details = json!({"source_message_id":"different-message"});
    assert!(matches!(
        fixture.store.write_event(&fixture.worker, conflict),
        Err(StateError::WorkEventConflict(_))
    ));

    let projection = fixture.store.query_run("run-a").unwrap();
    assert_eq!(
        projection
            .events
            .iter()
            .filter(|event| event.event_id == "worker-started-424")
            .count(),
        1
    );
}

fn start_request(
    path: &std::path::Path,
    expected_runtime_revision: u64,
) -> CommitDeliveryStartRequest {
    let bytes = fs::read(path).unwrap();
    CommitDeliveryStartRequest {
        event_id: "transport-started-2".into(),
        transport_receipt_id: "start-receipt-2".into(),
        run_id: "run-a".into(),
        go_id: "GO-001".into(),
        cell_id: "CELL-001".into(),
        attempt: 1,
        plan_revision: 1,
        expected_runtime_revision,
        message_id: "message-2".into(),
        token_sequence: 2,
        from_role_instance_id: "supervisor-a".into(),
        to_role_instance_id: "checker-a".into(),
        endpoint_version: 1,
        payload_type: "CELL_ASSIGNMENT".into(),
        payload_sha256: "b".repeat(64),
        start_evidence: DeliveryStartEvidence {
            evidence_id: "start-evidence-2".into(),
            stored_path: path.to_string_lossy().into_owned(),
            sha256: format!("{:x}", Sha256::digest(bytes)),
            message_id: "message-2".into(),
            endpoint_sha256: "c".repeat(64),
            envelope_sha256: "d".repeat(64),
            native_status: NativeStartStatus::Started,
        },
        occurred_at: "2026-09-22T00:00:02Z".into(),
    }
}

struct Fixture {
    root: tempfile::TempDir,
    store: StateStore,
    supervisor: slk_state_core::auth::Credential,
    worker: slk_state_core::auth::Credential,
}

impl Fixture {
    fn new_423() -> Self {
        let root = tempfile::tempdir().unwrap();
        let store = StateStore::new(root.path());
        let initialized = store.init_run(init_request()).unwrap();
        let checker = store
            .register_role(
                &initialized.supervisor_credential,
                register_role("register-checker", "checker-a", Role::Checker),
            )
            .unwrap();
        let worker = store
            .register_role(
                &checker.credential,
                register_role("register-worker", "worker-a", Role::Worker),
            )
            .unwrap();
        let connection = slk_state_core::schema::open_database(root.path()).unwrap();
        connection
            .execute(
                "UPDATE runs SET slk_version='4.2.3' WHERE run_id='run-a'",
                [],
            )
            .unwrap();
        Self {
            root,
            store,
            supervisor: initialized.supervisor_credential,
            worker: worker.credential,
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

fn init_request() -> InitRunRequest {
    InitRunRequest {
        project: ProjectIdentity {
            project_id: "project-a".into(),
            name: "Project A".into(),
            repository_url: None,
            last_known_path: "D:/ProjectA".into(),
        },
        run_id: "run-a".into(),
        predecessor_run_id: None,
        run_name: Some("Run A".into()),
        run_description: Some("Runtime snapshot test".into()),
        source_kind: Some("solo".into()),
        source_project_name: None,
        goal: "Test one bounded Run".into(),
        boundaries: json!({"write_scope":["src/"]}),
        go_nodes: vec![GoDefinition {
            go_id: "GO-001".into(),
            ordinal: 1,
            title: "GO".into(),
            objective: "Complete".into(),
        }],
        cell_nodes: vec![CellDefinition {
            go_id: "GO-001".into(),
            cell_id: "CELL-001".into(),
            ordinal: 1,
            title: "CELL".into(),
            objective: "Implement".into(),
        }],
        supervisor: role("supervisor-a", Role::Supervisor),
        supervisor_endpoint: endpoint("session-supervisor-a", "codex-app-server"),
        occurred_at: "2026-09-22T00:00:00Z".into(),
    }
}

fn register_role(event_id: &str, id: &str, role_kind: Role) -> RegisterRoleRequest {
    RegisterRoleRequest {
        event_id: event_id.into(),
        run_id: "run-a".into(),
        identity: role(id, role_kind),
        endpoint: match role_kind {
            Role::Checker => endpoint(&format!("session-{id}"), "ocrv-checker"),
            Role::Worker => endpoint(&format!("session-{id}"), "dsh-worker"),
            _ => unreachable!(),
        },
        occurred_at: "2026-09-22T00:00:01Z".into(),
    }
}

fn role(id: &str, role_kind: Role) -> RoleIdentity {
    let (runtime, provider, model, reasoning) = match role_kind {
        Role::Supervisor => ("codex", "openai", "gpt-5.6-sol", "xhigh"),
        Role::Checker => (
            "ocrv",
            "dashscope-tokenplan",
            "qwen3.8-max",
            "provider-default",
        ),
        Role::Worker => ("dsh", "deepseek", "deepseek-v4-flash", "provider-default"),
        Role::Overwatcher => unreachable!(),
    };
    RoleIdentity {
        role_instance_id: id.into(),
        role: role_kind,
        agent_runtime: runtime.into(),
        provider: provider.into(),
        model: model.into(),
        reasoning: reasoning.into(),
        session_id: format!("session-{id}"),
    }
}

fn endpoint(session_id: &str, adapter: &str) -> EndpointIdentity {
    EndpointIdentity {
        endpoint_version: 1,
        transport_adapter: adapter.into(),
        host_identity: "host-a".into(),
        session_id: session_id.into(),
        native_address: json!({"session_id":session_id}),
    }
}
