use serde_json::json;

use slk_state_core::evidence::{EvidenceRequest, EvidenceState};
use slk_state_core::model::{
    CellDefinition, EndpointIdentity, GoDefinition, InitRunRequest, ProjectIdentity, Role,
    RoleIdentity,
};
use slk_state_core::write::StateStore;

#[test]
fn evidence_is_copied_under_project_run_and_hash_checked() {
    let root = tempfile::tempdir().unwrap();
    let source_root = tempfile::tempdir().unwrap();
    let source = source_root.path().join("proof.txt");
    std::fs::write(&source, b"proof").unwrap();
    let store = StateStore::new(root.path());
    let initialized = store.init_run(init_request()).unwrap();

    let saved = store
        .register_evidence(
            &initialized.supervisor_credential,
            EvidenceRequest {
                evidence_id: "proof-a".into(),
                run_id: "run-a".into(),
                go_id: Some("GO-001".into()),
                cell_id: Some("CELL-001".into()),
                evidence_type: "test-output".into(),
                source_path: source,
                occurred_at: "2026-09-20T00:00:01Z".into(),
            },
        )
        .unwrap();

    assert!(saved
        .stored_path
        .starts_with(root.path().join("evidence/project-a/run-a")));
    assert_eq!(
        store.verify_evidence("proof-a").unwrap(),
        EvidenceState::PresentAndMatching
    );
    std::fs::write(&saved.stored_path, b"changed").unwrap();
    assert_eq!(
        store.verify_evidence("proof-a").unwrap(),
        EvidenceState::HashMismatch
    );
}

#[test]
fn invalid_evidence_id_reports_the_field_and_accepted_characters() {
    let root = tempfile::tempdir().unwrap();
    let source_root = tempfile::tempdir().unwrap();
    let source = source_root.path().join("proof.txt");
    std::fs::write(&source, b"proof").unwrap();
    let store = StateStore::new(root.path());
    let initialized = store.init_run(init_request()).unwrap();

    let error = store
        .register_evidence(
            &initialized.supervisor_credential,
            EvidenceRequest {
                evidence_id: "proof+0800".into(),
                run_id: "run-a".into(),
                go_id: Some("GO-001".into()),
                cell_id: Some("CELL-001".into()),
                evidence_type: "test-output".into(),
                source_path: source,
                occurred_at: "2026-09-20T00:00:01Z".into(),
            },
        )
        .unwrap_err();

    assert_eq!(
        error.to_string(),
        "evidence source or identity is invalid: evidence_id must be 1-128 ASCII letters, digits, '-', '_' or '.'"
    );
}

fn summary_request(original_id: &str) -> slk_state_core::closeout::RecordCloseoutSummaryRequest {
    slk_state_core::closeout::RecordCloseoutSummaryRequest {
        run_id:"run-a".into(),original_id:original_id.into(),body:"Accepted result; no blockers.".into(),
        recorded_at:"2026-10-18T00:00:00Z".into(),device_signature:None,
    }
}

#[test]
fn unchanged_summary_with_a_new_request_id_reuses_the_current_source() {
    let root = tempfile::tempdir().unwrap();
    let store = StateStore::new(root.path());
    let supervisor = store.init_run(init_request()).unwrap().supervisor_credential;
    let first = store.record_closeout_summary(&supervisor, summary_request("first")).unwrap();
    let before = store.query_run("run-a").unwrap();
    let duplicate = store.record_closeout_summary(&supervisor, summary_request("accidental-new-id")).unwrap();
    assert_eq!(duplicate.status, "summary_replayed");
    assert_eq!(duplicate.original_id, first.original_id);
    assert_eq!(duplicate.closeout_summary, first.closeout_summary);
    assert_eq!(store.query_run("run-a").unwrap(), before);
    // A genuine correction and a later reversion are both new records.
    let mut correction = summary_request("correction");
    correction.body = "Corrected result.".into();
    assert_eq!(store.record_closeout_summary(&supervisor, correction).unwrap().closeout_summary.source_revision, 2);
    assert_eq!(store.record_closeout_summary(&supervisor, summary_request("reversion")).unwrap().closeout_summary.source_revision, 3);
}

#[test]
fn summary_signature_only_correction_concurrent_retries_and_large_body_are_immutable() {
    use slk_state_core::closeout::DeviceSignature;
    let root=tempfile::tempdir().unwrap();let store=StateStore::new(root.path());
    let supervisor=store.init_run(init_request()).unwrap().supervisor_credential;
    let mut request=summary_request("first");request.body="结果\n".repeat(100_000);
    let first=store.record_closeout_summary(&supervisor,request.clone()).unwrap();
    let before=store.query_run("run-a").unwrap();
    let results=std::thread::scope(|scope| {
        let handles=(0..4).map(|_| {let store=&store;let supervisor=&supervisor;let request=request.clone();scope.spawn(move||store.record_closeout_summary(supervisor,request).unwrap())}).collect::<Vec<_>>();
        handles.into_iter().map(|h|h.join().unwrap()).collect::<Vec<_>>()
    });
    assert!(results.iter().all(|r|r.status=="summary_replayed" && r.closeout_summary==first.closeout_summary));
    assert_eq!(store.query_run("run-a").unwrap(),before);
    request.original_id="signature-correction".into();
    request.device_signature=Some(DeviceSignature {computer_name:Some("host-b".into()),ip_address:None,os_version:None});
    let second=StateStore::new(root.path()).record_closeout_summary(&supervisor,request).unwrap();
    assert_eq!(second.closeout_summary.source_revision,2);
    assert_eq!(second.closeout_summary.body,first.closeout_summary.body);
    assert_ne!(second.closeout_summary.content_sha256,first.closeout_summary.content_sha256);
    assert_eq!(store.query_run("run-a").unwrap().runtime_snapshot,before.runtime_snapshot);
    let source=store.query_run("run-a").unwrap().evidence.into_iter().find(|e|e.evidence_id==first.closeout_summary.source_id).unwrap();
    assert_eq!(store.verify_evidence(&source.evidence_id).unwrap(),EvidenceState::PresentAndMatching);
}

#[test]
fn summary_retries_after_durable_original_rollback_and_an_intervening_summary() {
    let root = tempfile::tempdir().unwrap();
    let store = StateStore::new(root.path());
    let supervisor = store.init_run(init_request()).unwrap().supervisor_credential;
    let before = store.query_run("run-a").unwrap();
    let request = summary_request("retry-original");
    let db = slk_state_core::schema::open_database(root.path()).unwrap();
    // Fail after the durable original exists, but before its evidence transaction commits.
    db.execute_batch("CREATE TRIGGER fail_summary_insert BEFORE INSERT ON evidence
        WHEN NEW.evidence_type='run_closeout_summary'
        BEGIN SELECT RAISE(ABORT, 'synthetic summary transaction failure'); END;").unwrap();
    let error = store.record_closeout_summary(&supervisor, request.clone()).unwrap_err();
    assert!(error.to_string().contains("synthetic summary transaction failure"));
    assert_eq!(store.query_run("run-a").unwrap(), before);
    let directory = root.path().join("evidence/project-a/run-a");
    let original_paths = std::fs::read_dir(&directory).unwrap()
        .map(|entry| entry.unwrap().path()).collect::<Vec<_>>();
    assert_eq!(original_paths.len(), 1);
    let uncommitted_path = &original_paths[0];
    let uncommitted_bytes = std::fs::read(uncommitted_path).unwrap();
    assert!(store.record_closeout_summary(&supervisor, request.clone()).is_err());
    assert_eq!(std::fs::read_dir(&directory).unwrap().count(), 1);
    assert_eq!(std::fs::read(uncommitted_path).unwrap(), uncommitted_bytes);
    db.execute_batch("DROP TRIGGER fail_summary_insert;").unwrap();
    let mut intervening = summary_request("intervening");
    intervening.body = "An independently corrected conclusion.".into();
    let other = store.record_closeout_summary(&supervisor, intervening).unwrap();
    assert_eq!(other.closeout_summary.source_revision, 1);

    let recovered = StateStore::new(root.path())
        .record_closeout_summary(&supervisor, request.clone()).unwrap();
    assert_eq!(recovered.status, "summary_recorded");
    assert_eq!(recovered.closeout_summary.source_revision, 2);
    assert_eq!(std::fs::read(uncommitted_path).unwrap(), uncommitted_bytes);
    let replay = store.record_closeout_summary(&supervisor, request).unwrap();
    assert_eq!(replay.status, "summary_replayed");
    assert_eq!(replay.closeout_summary, recovered.closeout_summary);
    let after = store.query_run("run-a").unwrap();
    assert_eq!(after.closeout_summary.as_ref(), Some(&recovered.closeout_summary));
    assert_eq!(after.evidence.len(), 2);
    assert_eq!(after.events, before.events);
    assert_eq!(after.runtime_snapshot, before.runtime_snapshot);
    assert_eq!(after.token_history, before.token_history);
    assert_eq!(after.plan_revisions, before.plan_revisions);
    assert_eq!(after.summary, before.summary);
    assert_eq!(store.verify_evidence(&recovered.closeout_summary.source_id).unwrap(),
        EvidenceState::PresentAndMatching);
}

#[test]
fn summary_requires_original_creator_and_exact_active_endpoint_not_just_supervisor_role() {
    let root=tempfile::tempdir().unwrap();let store=StateStore::new(root.path());
    let supervisor=store.init_run(init_request()).unwrap().supervisor_credential;
    let db=slk_state_core::schema::open_database(root.path()).unwrap();
    db.execute("UPDATE role_endpoints SET session_id='other-session' WHERE role_instance_id='supervisor-a'",[]).unwrap();
    assert!(store.record_closeout_summary(&supervisor,summary_request("invalid-endpoint")).is_err());
    db.execute("UPDATE role_endpoints SET session_id='thread-a' WHERE role_instance_id='supervisor-a'",[]).unwrap();
    db.execute("UPDATE role_instances SET lifecycle='replaced' WHERE role_instance_id='supervisor-a'",[]).unwrap();
    db.execute("INSERT INTO role_instances (role_instance_id,run_id,role,agent_runtime,provider,model,reasoning,session_id,lifecycle,created_at) VALUES ('successor','run-a','supervisor','codex','openai','gpt-6.1-sol','high','thread-b','active','2026-10-18T00:00:00Z')",[]).unwrap();
    db.execute("INSERT INTO role_endpoints (run_id,role_instance_id,endpoint_version,transport_adapter,host_identity,session_id,native_address_json,state,created_at) VALUES ('run-a','successor',1,'codex-app-server','host-a','thread-b','{}','active','2026-10-18T00:00:00Z')",[]).unwrap();
    let successor=slk_state_core::auth::issue_credential(&db,"run-a","successor","2026-10-18T00:00:00Z").unwrap().credential;
    assert!(store.record_closeout_summary(&successor,summary_request("not-creator")).is_err());
    assert!(store.record_closeout_summary(&supervisor,summary_request("revoked-creator")).is_err());
    assert!(store.query_run("run-a").unwrap().evidence.is_empty());
}

#[test]
fn summary_rejects_checker_worker_and_generic_reserved_evidence_without_advancing_state() {
    let root=tempfile::tempdir().unwrap();let store=StateStore::new(root.path());
    store.init_run(init_request()).unwrap();
    let db=slk_state_core::schema::open_database(root.path()).unwrap();
    let source=root.path().join("fake-summary.json");std::fs::write(&source,b"{}").unwrap();
    for role in ["checker","worker"] {
        db.execute("INSERT INTO role_instances (role_instance_id,run_id,role,agent_runtime,provider,model,reasoning,session_id,lifecycle,created_at) VALUES (?1,'run-a',?1,'synthetic','synthetic','synthetic','',?1,'active','2026-10-18T00:00:00Z')",[role]).unwrap();
        let credential=slk_state_core::auth::issue_credential(&db,"run-a",role,"2026-10-18T00:00:00Z").unwrap().credential;
        let before=store.query_run("run-a").unwrap();
        assert!(store.record_closeout_summary(&credential,summary_request(role)).is_err());
        assert!(store.register_evidence(&credential,EvidenceRequest {evidence_id:role.into(),run_id:"run-a".into(),go_id:None,cell_id:None,evidence_type:"run_closeout_summary".into(),source_path:source.clone(),occurred_at:"2026-10-18T00:00:00Z".into()}).is_err());
        assert_eq!(store.query_run("run-a").unwrap(),before);
    }
}

#[test]
fn ordinary_engineering_evidence_still_advances_revision() {
    let root=tempfile::tempdir().unwrap();let store=StateStore::new(root.path());
    let supervisor=store.init_run(init_request()).unwrap().supervisor_credential;
    let before=store.query_run("run-a").unwrap().runtime_snapshot.unwrap();
    let source=root.path().join("engineering.txt");std::fs::write(&source,b"actual engineering evidence").unwrap();
    store.register_evidence(&supervisor,EvidenceRequest {evidence_id:"engineering".into(),run_id:"run-a".into(),go_id:None,cell_id:None,evidence_type:"test-output".into(),source_path:source,occurred_at:"2026-10-18T00:00:00Z".into()}).unwrap();
    let after=store.query_run("run-a").unwrap().runtime_snapshot.unwrap();
    assert_eq!(after.runtime_revision,before.runtime_revision+1);
    assert_eq!(after.latest_event_id,"engineering");
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
        run_name: None,
        run_description: None,
        source_kind: None,
        source_project_name: None,
        goal: "Goal".into(),
        boundaries: json!({}),
        go_nodes: vec![GoDefinition {
            go_id: "GO-001".into(),
            ordinal: 1,
            title: "GO".into(),
            objective: "Objective".into(),
        }],
        cell_nodes: vec![CellDefinition {
            go_id: "GO-001".into(),
            cell_id: "CELL-001".into(),
            ordinal: 1,
            title: "CELL".into(),
            objective: "Objective".into(),
        }],
        supervisor: RoleIdentity {
            role_instance_id: "supervisor-a".into(),
            role: Role::Supervisor,
            agent_runtime: "codex".into(),
            provider: "openai".into(),
            model: "gpt-6.1-sol".into(),
            reasoning: "xhigh".into(),
            session_id: "thread-a".into(),
        },
        supervisor_endpoint: EndpointIdentity {
            endpoint_version: 1,
            transport_adapter: "codex-app-server".into(),
            host_identity: "host-a".into(),
            session_id: "thread-a".into(),
            native_address: json!({"thread_id":"thread-a"}),
        },
        occurred_at: "2026-09-20T00:00:00Z".into(),
    }
}
