use std::thread;

use serde_json::json;
use slk_state_core::model::{
    CellDefinition, EndpointIdentity, GoDefinition, InitRunRequest, ProjectIdentity, Role,
    RoleIdentity,
};
use slk_state_core::write::StateStore;

#[test]
fn distinct_runs_initialize_concurrently_without_state_crossover() {
    let root = tempfile::tempdir().unwrap();
    let store = StateStore::new(root.path());
    let first = store.clone();
    let second = store.clone();

    let a = thread::spawn(move || first.init_run(request("run-a", "project-a")));
    let b = thread::spawn(move || second.init_run(request("run-b", "project-b")));
    a.join().unwrap().unwrap();
    b.join().unwrap().unwrap();

    assert_eq!(
        store.current_token("run-a").unwrap().owner_role_instance_id,
        "supervisor-run-a"
    );
    assert_eq!(
        store.current_token("run-b").unwrap().owner_role_instance_id,
        "supervisor-run-b"
    );
    assert_eq!(store.run_count().unwrap(), 2);
}

#[test]
fn conflicting_initialization_of_one_run_has_one_winner() {
    let root = tempfile::tempdir().unwrap();
    let first = StateStore::new(root.path());
    let second = first.clone();
    let a = thread::spawn(move || first.init_run(request("run-a", "project-a")));
    let b = thread::spawn(move || second.init_run(request("run-a", "project-a")));
    let outcomes = [a.join().unwrap(), b.join().unwrap()];

    assert_eq!(outcomes.iter().filter(|result| result.is_ok()).count(), 1);
    assert_eq!(StateStore::new(root.path()).run_count().unwrap(), 1);
}

fn request(run_id: &str, project_id: &str) -> InitRunRequest {
    let role_instance_id = format!("supervisor-{run_id}");
    InitRunRequest {
        project: ProjectIdentity {
            project_id: project_id.into(),
            name: project_id.into(),
            repository_url: None,
            last_known_path: format!("D:/{project_id}"),
        },
        run_id: run_id.into(),
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
            role_instance_id,
            role: Role::Supervisor,
            agent_runtime: "codex".into(),
            provider: "openai".into(),
            model: "sol".into(),
            reasoning: "xhigh".into(),
            session_id: format!("session-{run_id}"),
        },
        supervisor_endpoint: EndpointIdentity {
            endpoint_version: 1,
            transport_adapter: "codex-app-server".into(),
            host_identity: "host-a".into(),
            session_id: format!("session-{run_id}"),
            native_address: json!({"thread_id":run_id}),
        },
        occurred_at: "2026-09-20T00:00:00Z".into(),
    }
}
