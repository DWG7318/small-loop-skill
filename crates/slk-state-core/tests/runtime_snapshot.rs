use std::fs;

use serde_json::json;
use sha2::{Digest, Sha256};

use slk_state_core::auth::StateError;
use slk_state_core::model::{
    CellDefinition, CommitDeliveryStartRequest, DeliveryStartEvidence, EndpointIdentity, EventType,
    EvidenceReference, GoDefinition, InitRunRequest, NativeStartStatus, ProjectIdentity,
    RegisterRoleRequest, ReviseRoleModelRequest, Role, RoleIdentity, TokenHandoffRequest,
    WriteRequest,
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
fn administrative_model_revision_preserves_latest_engineering_message() {
    let fixture = Fixture::new_423();
    let start_path = fixture.root.path().join("started-model-revision.json");
    fs::write(&start_path, br#"{"status":"started"}"#).unwrap();
    fixture
        .store
        .commit_delivery_start(
            &fixture.supervisor,
            start_request(&start_path, fixture.runtime_revision()),
        )
        .unwrap();
    let connection = slk_state_core::schema::open_database(fixture.root.path()).unwrap();
    connection
        .execute(
            "UPDATE role_instances SET model='gpt-5.6-sol' WHERE run_id='run-a' AND role='supervisor'",
            [],
        )
        .unwrap();
    let evidence_path = fixture.root.path().join("owner-model-choice.txt");
    fs::write(&evidence_path, b"Owner selected gpt-6.1-sol xhigh").unwrap();
    let evidence_sha256 = format!("{:x}", Sha256::digest(fs::read(&evidence_path).unwrap()));

    fixture
        .store
        .revise_role_model(
            &fixture.supervisor,
            ReviseRoleModelRequest {
                event_id: "model-revised-after-delivery".into(),
                run_id: "run-a".into(),
                role_instance_id: "supervisor-a".into(),
                expected_runtime_revision: fixture.runtime_revision(),
                model: "gpt-6.1-sol".into(),
                reasoning: "xhigh".into(),
                owner_evidence: EvidenceReference {
                    path: evidence_path.to_string_lossy().into_owned(),
                    sha256: evidence_sha256,
                },
                reason: "Owner model policy correction".into(),
                occurred_at: "2026-10-05T00:00:00Z".into(),
            },
        )
        .unwrap();

    let snapshot = fixture
        .store
        .query_run("run-a")
        .unwrap()
        .runtime_snapshot
        .unwrap();
    assert_eq!(snapshot.latest_event_id, "model-revised-after-delivery");
    assert_eq!(snapshot.latest_message_id.as_deref(), Some("message-2"));
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
fn slk_435_and_later_reject_legacy_started_marker_and_accept_exact_native_v2() {
    for method_version in ["4.3.5", "4.3.6", "4.4.0", "4.4.1", "4.4.2"] {
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
    checker: slk_state_core::auth::Credential,
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
            checker: checker.credential,
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

#[test]
fn recovered_incomplete_after_independent_fail_preserves_causality_token_and_replay() {
    let home = tempfile::tempdir().unwrap();
    let previous = std::env::var_os("CODEX_HOME");
    std::env::set_var("CODEX_HOME", home.path());
    struct Restore(Option<std::ffi::OsString>);
    impl Drop for Restore {
        fn drop(&mut self) {
            if let Some(value) = &self.0 {
                std::env::set_var("CODEX_HOME", value);
            } else {
                std::env::remove_var("CODEX_HOME");
            }
        }
    }
    let _restore = Restore(previous);
    for fault in [
        "none",
        "ordinary-v2",
        "wrong-target",
        "late-recovery",
        "wrong-candidate",
        "false-platform",
        "wrapper-turn",
        "wrapper-output",
        "ack-first",
    ] {
        let fixture = Fixture::new_423();
        let db = slk_state_core::schema::open_database(fixture.root.path()).unwrap();
        db.execute(
            "UPDATE runs SET slk_version='4.4.2' WHERE run_id='run-a'",
            [],
        )
        .unwrap();
        drop(db);
        let path = fixture.root.path().join("checker-start.json");
        fs::write(&path, serde_json::to_vec(&json!({"schema_version":"slk.native-start/v2","status":"STARTED",
            "adapter":"ocrv-checker","run_id":"run-a","cell_id":"CELL-001","message_id":"message-2",
            "request_sha256":"b".repeat(64),"native_request_sha256":"e".repeat(64),"observed_at":"2026-09-22T00:00:02Z",
            "process":{"pid":4321,"creation_time":"win-filetime:12345"},
            "native_task":{"kind":"ocrv-review","id":"review-a","status":"RUNNING"}})).unwrap()).unwrap();
        fixture
            .store
            .commit_delivery_start(
                &fixture.supervisor,
                start_request(&path, fixture.runtime_revision()),
            )
            .unwrap();
        let incomplete = WriteRequest {
            event_id: "incomplete-a".into(),
            run_id: "run-a".into(),
            go_id: Some("GO-001".into()),
            cell_id: Some("CELL-001".into()),
            attempt: Some(1),
            plan_revision: 1,
            role_instance_id: "checker-a".into(),
            event_type: EventType::D1Incomplete,
            details: json!({"verdict":"INCOMPLETE","candidate_message_id":"candidate-a",
                "native_terminal_sha256":"a".repeat(64),"native_result_sha256":"b".repeat(64)}),
            corrects_event_id: None,
            occurred_at: "2026-09-22T00:01:00Z".into(),
        };
        fixture
            .store
            .write_event(&fixture.checker, incomplete)
            .unwrap();
        let mut request = recovery_request(&fixture, home.path(), fault);
        let failed = WriteRequest {
            event_id: "independent-fail-a".into(),
            run_id: "run-a".into(),
            go_id: Some("GO-001".into()),
            cell_id: Some("CELL-001".into()),
            attempt: Some(2),
            plan_revision: 1,
            role_instance_id: "checker-a".into(),
            event_type: EventType::D1Failed,
            corrects_event_id: Some("incomplete-a".into()),
            occurred_at: "2026-09-22T00:03:00Z".into(),
            details: json!({"verdict":"FAIL","candidate_message_id":"candidate-a","independent_fail":{
                "schema_version":"slk.ocrv-independent-fail/v1","d1_incomplete_event_id":"incomplete-a",
                "source_attempt":1,"engineering_attempt":2,"candidate_commit":"c".repeat(40),"occurred_at":"2026-09-22T00:03:00Z"}}),
        };
        if fault == "ack-first" {
            fixture
                .store
                .commit_delivery_start(&fixture.checker, request)
                .unwrap();
            assert!(matches!(
                fixture.store.write_event(&fixture.checker, failed),
                Err(StateError::TokenOwnerMismatch { .. })
            ));
            continue;
        }
        fixture.store.write_event(&fixture.checker, failed).unwrap();
        let before = fixture.runtime_revision();
        assert!(
            matches!(
                fixture
                    .store
                    .commit_delivery_start(&fixture.checker, request.clone()),
                Err(StateError::RuntimeRevisionMismatch { .. })
            ) || matches!(fault, "false-platform" | "wrapper-turn" | "wrapper-output")
        );
        request.expected_runtime_revision = before;
        let result = fixture
            .store
            .commit_delivery_start(&fixture.checker, request.clone());
        if fault != "none" {
            assert!(result.is_err(), "{fault} must fail closed");
            assert_eq!(fixture.runtime_revision(), before);
            assert_eq!(
                fixture
                    .store
                    .current_token("run-a")
                    .unwrap()
                    .owner_role_instance_id,
                "checker-a"
            );
        } else {
            let result = result.unwrap();
            assert_eq!(result.token.owner_role_instance_id, "supervisor-a");
            assert_eq!(result.token.sequence, 3);
            let count = fixture.store.query_run("run-a").unwrap().events.len();
            let replay = fixture
                .store
                .commit_delivery_start(&fixture.checker, request)
                .unwrap();
            assert_eq!(replay.status, "IDEMPOTENT_REPLAY");
            assert_eq!(
                fixture.store.query_run("run-a").unwrap().events.len(),
                count
            );
            let original = fixture.root.path().join("attempts/run-a/original-a");
            assert!(!original.join("started.json").exists());
            assert!(original.join("failed.json").exists());
        }
    }
}

fn recovery_request(
    fixture: &Fixture,
    home: &std::path::Path,
    fault: &str,
) -> CommitDeliveryStartRequest {
    fn digest(data: &[u8]) -> String {
        format!("{:x}", Sha256::digest(data))
    }
    fn put(root: &std::path::Path, name: &str, value: &serde_json::Value) -> String {
        fs::create_dir_all(root).unwrap();
        let data = serde_json::to_vec(value).unwrap();
        fs::write(root.join(name), &data).unwrap();
        digest(&data)
    }
    let original = fixture.root.path().join("attempts/run-a/original-a");
    let root = original.join("recovery/desktop-current-turn");
    let endpoint = json!({"schema_version":"slk.transport-endpoint/v1","run_id":"run-a","role":"supervisor",
        "role_instance_id":"supervisor-a","agent_runtime":"codex","adapter":"codex-app-server","host_id":"host-a",
        "endpoint_version":1,"state":"active","address":{"thread_id":"session-supervisor-a"}});
    let payload = json!({"d1_incomplete_event_id":if fault=="wrong-target" {"another-incomplete"} else {"incomplete-a"},
        "candidate_message_id":"candidate-a","candidate_payload":{"candidate":{"kind":"commit","commit":if fault=="wrong-candidate" {"d".repeat(40)} else {"c".repeat(40)}}},
        "native_terminal_sha256":"a".repeat(64),"native_result_sha256":"b".repeat(64)});
    let payload_sha = digest(&serde_json::to_vec(&payload).unwrap());
    let envelope = json!({"schema_version":"slk.transport-envelope/v1","run_id":"run-a","go_id":"GO-001","cell_id":"CELL-001",
        "message_id":"original-a","token_sequence":3,"sender_role":"checker","sender_role_instance_id":"checker-a",
        "receiver_role":"supervisor","receiver_role_instance_id":"supervisor-a","receiver_endpoint_version":1,
        "payload_type":"D1_INCOMPLETE_ESCALATION","payload_sha256":payload_sha,"payload":payload});
    let ep_sha = put(&original, "endpoint.json", &endpoint);
    let env_sha = put(&original, "envelope.json", &envelope);
    let failure = json!({"status":"failed","error_code":"CODEX_ACTIVE_WRITER_UNRESOLVED","adapter":"codex-app-server","run_id":"run-a","message_id":"original-a"});
    put(&original, "failed.json", &failure);
    let retry = original.join("recovery/exact-1/run-a/original-a");
    put(&retry, "endpoint.json", &endpoint);
    put(&retry, "envelope.json", &envelope);
    put(&retry, "failed.json", &failure);
    let message = json!({"schema_version":"slk.transport-desktop-current-turn-message/v1","challenge":"f".repeat(64),
        "recovery_of_message_id":"original-a","recovery_message_id":"recovery-a","run_id":"run-a","go_id":"GO-001","cell_id":"CELL-001",
        "token_sequence":3,"sender_role":"checker","sender_role_instance_id":"checker-a","receiver_role":"supervisor",
        "receiver_role_instance_id":"supervisor-a","receiver_endpoint_version":1,"payload_type":"D1_INCOMPLETE_ESCALATION","payload_sha256":payload_sha});
    let prompt=format!("SLK Desktop current-turn recovery. Treat this as one new auditable delivery bound to the preserved failed Checker message; do not replay or rewrite the original.\n<slk-desktop-current-turn-recovery>{}</slk-desktop-current-turn-recovery>", serde_json::to_string(&message).unwrap());
    let prompt_sha = digest(prompt.as_bytes());
    let prepared = json!({"schema_version":"slk.transport-desktop-current-turn-request/v1","status":"PREPARED","original_message_id":"original-a",
        "recovery_message_id":"recovery-a","run_id":"run-a","go_id":"GO-001","cell_id":"CELL-001","token_sequence":3,
        "sender_role":"checker","sender_role_instance_id":"checker-a","receiver_role":"supervisor","receiver_role_instance_id":"supervisor-a",
        "receiver_endpoint_version":1,"payload_type":"D1_INCOMPLETE_ESCALATION","payload_sha256":payload_sha,"endpoint_sha256":ep_sha,
        "envelope_sha256":env_sha,"target_thread_id":"session-supervisor-a","challenge":"f".repeat(64),"prompt":prompt,"prompt_sha256":prompt_sha});
    let prepared_sha = put(&root, "request.json", &prepared);
    let host = json!({"schema_version":"slk.transport-desktop-current-turn-host-receipt/v1","status":"PLATFORM_READBACK_CONFIRMED",
        "request_sha256":digest(&serde_json::to_vec(&prepared).unwrap()),"host_thread_id":"session-supervisor-a","host_turn_id":"turn-a","host_session_id":"session-a",
        "target_thread_id":"session-supervisor-a","before":{"thread_status":"active","turn_id":"turn-a","turn_status":"inProgress"},
        "after":{"thread_status":"active","turn_id":"turn-a","turn_status":"inProgress","platform_item_id":"fco-recovery-a",
            "item_type":"functionCallOutput","item_name":"send_message_to_thread","item_namespace":"codex_app","message_sha256":prompt_sha}});
    let host_sha = put(&root, "host-receipt.json", &host);
    let recovery = json!({"schema_version":"slk.transport-desktop-current-turn-recovery/v1","recovery_of_message_id":"original-a","recovery_message_id":"recovery-a",
        "run_id":"run-a","thread_id":"session-supervisor-a","turn_id":"turn-a","platform_item_id":"fco-recovery-a","payload_sha256":payload_sha,
        "endpoint_sha256":ep_sha,"envelope_sha256":env_sha,"status":"started"});
    let recovery_sha = put(&root, "recovery.json", &recovery);
    let mut started = json!({"schema_version":"slk.native-start/v2","status":"STARTED","adapter":"codex-app-server","run_id":"run-a","cell_id":"CELL-001",
        "message_id":"recovery-a","request_sha256":payload_sha,"native_request_sha256":prompt_sha,
        "observed_at":if fault=="late-recovery" {"2026-09-22T00:04:00Z"} else {"2026-09-22T00:02:00Z"},
        "process":{"pid":4321,"creation_time":"win-filetime:12345"},"native_task":{"kind":"codex-desktop-turn","id":"session-supervisor-a:turn-a:fco-recovery-a","status":"RUNNING"}});
    let started_sha = put(&root, "started.json", &started);
    let platform = home.join("sessions/2026/09/22/rollout-session-supervisor-a.jsonl");
    fs::create_dir_all(platform.parent().unwrap()).unwrap();
    let output=format!("<codex_delegation><source_thread_id>session-supervisor-a</source_thread_id><input>{}</input></codex_delegation>",
        prompt.replace('&',"&amp;").replace('<',"&lt;").replace('>',"&gt;"));
    fs::write(&platform,format!("{}\n{}\n{}\n",json!({"type":"session_meta","payload":{"id":"session-supervisor-a","originator":"Codex Desktop"}}),
        json!({"timestamp":"2026-09-22T00:02:00Z","type":"response_item","payload":{"type":"function_call_output","id":"fco-recovery-a","name":"send_message_to_thread",
            "namespace":"codex_app","output":if fault=="false-platform" {"not the delivery"} else {&output},
            "internal_chat_message_metadata_passthrough":{"turn_id":"turn-a"}}}),
        json!({"type":"event_msg","payload":{"type":"item_completed","thread_id":"session-supervisor-a",
            "turn_id":if fault=="wrapper-turn" {"wrong-turn"} else {"turn-a"},
            "item":{"type":"FunctionCallOutput","id":"fco-recovery-a","name":"send_message_to_thread",
                "namespace":"codex_app","output":if fault=="wrapper-output" {"wrong-output"} else {&output}}}}))).unwrap();
    let packet = json!({"schema_version":"slk.desktop-current-turn-start-evidence/v1","request_sha256":prepared_sha,
        "host_receipt_sha256":host_sha,"recovery_sha256":recovery_sha,"started_sha256":started_sha,"platform_record_path":platform});
    let (evidence_path, evidence_sha) = if fault == "ordinary-v2" {
        started["message_id"] = json!("original-a");
        let hash = put(&original, "started.json", &started);
        (original.join("started.json"), hash)
    } else {
        let hash = put(&root, "start-evidence.json", &packet);
        (root.join("start-evidence.json"), hash)
    };
    CommitDeliveryStartRequest {
        event_id: "recovered-transport-a".into(),
        transport_receipt_id: "recovered-receipt-a".into(),
        run_id: "run-a".into(),
        go_id: "GO-001".into(),
        cell_id: "CELL-001".into(),
        attempt: 1,
        plan_revision: 1,
        expected_runtime_revision: fixture.runtime_revision(),
        message_id: "original-a".into(),
        token_sequence: 3,
        from_role_instance_id: "checker-a".into(),
        to_role_instance_id: "supervisor-a".into(),
        endpoint_version: 1,
        payload_type: "D1_INCOMPLETE_ESCALATION".into(),
        payload_sha256: payload_sha,
        start_evidence: DeliveryStartEvidence {
            evidence_id: "recovered-evidence-a".into(),
            stored_path: evidence_path.to_string_lossy().into_owned(),
            sha256: evidence_sha,
            message_id: "original-a".into(),
            endpoint_sha256: ep_sha,
            envelope_sha256: env_sha,
            native_status: NativeStartStatus::Started,
        },
        occurred_at: "2026-09-22T00:05:00Z".into(),
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
        Role::Supervisor => ("codex", "openai", "gpt-6.1-sol", "xhigh"),
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
