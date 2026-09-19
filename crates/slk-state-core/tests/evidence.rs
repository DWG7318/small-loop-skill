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

fn init_request() -> InitRunRequest {
    InitRunRequest {
        project: ProjectIdentity {
            project_id: "project-a".into(),
            name: "Project A".into(),
            repository_url: None,
            last_known_path: "D:/ProjectA".into(),
        },
        run_id: "run-a".into(),
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
            model: "sol".into(),
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
