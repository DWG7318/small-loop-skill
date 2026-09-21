use slk_bi_desktop_lib::commands::{projects_from, runs_from, REGISTERED_READ_COMMANDS};
use slk_state_core::config::configure_at;
use slk_state_core::model::{
    CellDefinition, EndpointIdentity, GoDefinition, InitRunRequest, ProjectIdentity, Role,
    RoleIdentity,
};
use slk_state_core::write::StateStore;

#[test]
fn desktop_commands_read_the_configured_global_store_without_credentials() {
    let temp = tempfile::tempdir().unwrap();
    let config = temp.path().join("config.json");
    let data = temp.path().join("data");
    configure_at(&config, &data).unwrap();
    StateStore::new(&data).init_run(init_request()).unwrap();

    let projects = projects_from(&config).unwrap();
    let runs = runs_from(&config, Some("project-a".into())).unwrap();
    assert_eq!(projects["schema_version"], "slk.bi.projects/v1");
    assert_eq!(runs["runs"][0]["run_id"], "run-a");
    let serialized = serde_json::to_string(&(projects, runs)).unwrap();
    assert!(!serialized.contains("credential"));
}

#[test]
fn desktop_registers_only_the_eight_read_commands() {
    assert_eq!(
        REGISTERED_READ_COMMANDS,
        ["projects", "runs", "run", "graph", "roles", "plans", "events", "evidence"]
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
        run_name: None,
        run_description: None,
        source_kind: None,
        source_project_name: None,
        goal: "Read-only BI".into(),
        boundaries: serde_json::json!({}),
        go_nodes: vec![GoDefinition {
            go_id: "GO-001".into(),
            ordinal: 1,
            title: "First".into(),
            objective: "First".into(),
        }],
        cell_nodes: vec![CellDefinition {
            go_id: "GO-001".into(),
            cell_id: "CELL-001".into(),
            ordinal: 1,
            title: "First".into(),
            objective: "First".into(),
        }],
        supervisor: RoleIdentity {
            role_instance_id: "supervisor-a".into(),
            role: Role::Supervisor,
            agent_runtime: "codex".into(),
            provider: "openai".into(),
            model: "sol".into(),
            reasoning: "xhigh".into(),
            session_id: "session-supervisor".into(),
        },
        supervisor_endpoint: EndpointIdentity {
            endpoint_version: 1,
            transport_adapter: "native".into(),
            host_identity: "host-a".into(),
            session_id: "session-supervisor".into(),
            native_address: serde_json::json!({"thread_id":"private"}),
        },
        occurred_at: "2026-09-20T00:00:00Z".into(),
    }
}
