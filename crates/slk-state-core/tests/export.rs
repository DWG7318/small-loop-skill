use serde_json::json;

use slk_state_core::model::{
    BindOverwatcherRequest, CellDefinition, EndpointIdentity, GoDefinition, InitRunRequest,
    ObservationKind, ObservationMode, OperationalObservationRequest, ProjectIdentity, Role,
    RoleIdentity,
};
use slk_state_core::write::StateStore;

#[test]
fn markdown_export_is_byte_deterministic_and_has_complete_sections() {
    let root = tempfile::tempdir().unwrap();
    let store = StateStore::new(root.path());
    let initialized = store.init_run(init_request()).unwrap();
    let overwatcher = store
        .bind_overwatcher(
            &initialized.supervisor_credential,
            BindOverwatcherRequest {
                event_id: "bind-overwatcher-a".into(),
                run_id: "run-a".into(),
                identity: RoleIdentity {
                    role_instance_id: "overwatcher-a".into(),
                    role: Role::Overwatcher,
                    agent_runtime: "codex".into(),
                    provider: "openai".into(),
                    model: "gpt-5.6-sol".into(),
                    reasoning: "xhigh".into(),
                    session_id: "thread-overwatcher-a".into(),
                },
                endpoint: EndpointIdentity {
                    endpoint_version: 1,
                    transport_adapter: "codex-app-server".into(),
                    host_identity: "host-a".into(),
                    session_id: "thread-overwatcher-a".into(),
                    native_address: json!({"thread_id":"thread-overwatcher-a"}),
                },
                observation_mode: ObservationMode::ForegroundActiveTurn,
                cadence_seconds: 240,
                foreground_turn_id: "foreground-turn-a".into(),
                native_active_session_evidence_ref: "codex:thread-active:overwatcher-a".into(),
                reason: "one dedicated optional observer".into(),
                occurred_at: "2026-09-22T00:00:01Z".into(),
            },
        )
        .unwrap();
    store
        .record_observation(
            &overwatcher.credential,
            OperationalObservationRequest {
                observation_id: "observation-a".into(),
                run_id: "run-a".into(),
                go_id: Some("GO-001".into()),
                cell_id: Some("CELL-001".into()),
                attempt: Some(1),
                plan_revision: 1,
                role_instance_id: "overwatcher-a".into(),
                kind: ObservationKind::ActivityUnproven,
                related_event_id: None,
                message_id: Some("message-a".into()),
                evidence_refs: vec!["transport/message-a/attempt.json".into()],
                details: json!({"reason":"no fresh native execution evidence"}),
                occurred_at: "2026-09-22T00:00:02Z".into(),
            },
        )
        .unwrap();

    let first = store.export_run("run-a").unwrap();
    let first_bytes = std::fs::read(&first).unwrap();
    let second = store.export_run("run-a").unwrap();
    assert_eq!(first_bytes, std::fs::read(second).unwrap());

    let text = String::from_utf8(first_bytes).unwrap();
    for marker in [
        "Plan revisions",
        "GO-001",
        "CELL-001",
        "D0 / Worker",
        "D1 / Checker",
        "D2 / Supervisor",
        "Corrections and exemptions",
        "SLK TOKEN history",
        "Overwatcher binding",
        "Overwatch cycles",
        "Operational observations / Overwatcher",
        "ACTIVITY_UNPROVEN",
        "transport/message-a/attempt.json",
        "Evidence",
    ] {
        assert!(text.contains(marker), "missing {marker}");
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
        run_name: None,
        run_description: None,
        source_kind: None,
        source_project_name: None,
        goal: "Goal".into(),
        boundaries: json!({"scope":"src"}),
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
            model: "gpt-5.6-sol".into(),
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
