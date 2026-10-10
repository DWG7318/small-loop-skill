use slk_bi_desktop_lib::commands::{
    metadata, projects_from, runs_from, validate_sync_payload, REGISTERED_READ_COMMANDS,
};
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
fn repeated_desktop_cold_reads_keep_a_compatible_v8_store_unchanged() {
    let temp = tempfile::tempdir().unwrap();
    let config = temp.path().join("config.json");
    let data = temp.path().join("data");
    configure_at(&config, &data).unwrap();
    StateStore::new(&data).init_run(init_request()).unwrap();
    // The complete real V8 migration/read matrix is covered by state-core/schema.
    let database = slk_state_core::schema::open_database(&data).unwrap();
    database.pragma_update(None, "user_version", 8).unwrap();
    drop(database);
    let database_path = data.join("slk.db");
    let original = std::fs::read(&database_path).unwrap();
    let original_config = std::fs::read(&config).unwrap();
    for _ in 0..3 {
        assert_eq!(
            projects_from(&config).unwrap()["projects"][0]["project_id"],
            "project-a"
        );
        assert_eq!(
            runs_from(&config, None).unwrap()["runs"][0]["run_id"],
            "run-a"
        );
    }
    assert_eq!(std::fs::read(&database_path).unwrap(), original);
    assert_eq!(std::fs::read(&config).unwrap(), original_config);
    assert!(!data.join("backups").exists());
}

#[test]
fn desktop_registers_the_nine_read_only_projection_commands() {
    assert_eq!(
        REGISTERED_READ_COMMANDS,
        ["metadata", "projects", "runs", "run", "graph", "roles", "plans", "events", "evidence"]
    );
}

#[test]
fn metadata_exposes_bi_version_and_a_nonempty_device_identity_without_secrets() {
    let value = metadata().unwrap();
    assert_eq!(value["schema_version"], "slk.bi.metadata/v1");
    assert_eq!(value["bi_version"], "1.1.1");
    assert!(value["device_id"].as_str().unwrap().len() >= 3);
    assert!(value["device_name"].as_str().unwrap().len() >= 1);
    let serialized = value.to_string().to_ascii_lowercase();
    assert!(!serialized.contains("token"));
    assert!(!serialized.contains("password"));
}

#[test]
fn upload_payload_is_version_and_device_bound_before_network_use() {
    let valid = serde_json::json!({
        "schema_version":"slk.bi.upload/v1",
        "bi_version":"1.1.0",
        "upload_id":"upload-a",
        "generated_at":"2026-10-04T00:00:00Z",
        "device":{"device_id":"device-a","device_name":"Workstation A"},
        "runs":[]
    });
    assert!(validate_sync_payload(&valid, "device-a").is_ok());
    let mut current = valid.clone();
    current["bi_version"] = serde_json::json!("1.1.1");
    assert!(validate_sync_payload(&current, "device-a").is_ok());
    current["bi_version"] = serde_json::json!("9.0.0");
    assert_eq!(
        validate_sync_payload(&current, "device-a").unwrap_err(),
        "SLK_WEBBI_UPLOAD_VERSION_UNSUPPORTED"
    );
    assert_eq!(
        validate_sync_payload(&valid, "device-b").unwrap_err(),
        "SLK_WEBBI_DEVICE_INVALID"
    );
    let mut extra = valid.clone();
    extra["raw_logs"] = serde_json::json!(["secret"]);
    assert_eq!(
        validate_sync_payload(&extra, "device-a").unwrap_err(),
        "SLK_WEBBI_UPLOAD_INVALID"
    );
}

fn init_request() -> InitRunRequest {
    InitRunRequest {
        predecessor_run_id: None,
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
            model: "gpt-6.1-sol".into(),
            reasoning: "xhigh".into(),
            session_id: "session-supervisor".into(),
        },
        supervisor_endpoint: EndpointIdentity {
            endpoint_version: 1,
            transport_adapter: "codex-app-server".into(),
            host_identity: "host-a".into(),
            session_id: "session-supervisor".into(),
            native_address: serde_json::json!({"thread_id":"private"}),
        },
        occurred_at: "2026-09-20T00:00:00Z".into(),
    }
}
