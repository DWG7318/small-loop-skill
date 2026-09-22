use std::cell::Cell;
use std::rc::Rc;

use serde_json::json;

use slk_state_core::model::{
    CellDefinition, EndpointIdentity, GoDefinition, InitRunRequest, ProjectIdentity, Role,
    RoleIdentity,
};
use slk_state_core::query::WaitForChangeStatus;
use slk_state_core::write::StateStore;

#[test]
fn bounded_wait_returns_changed_or_timeout_without_a_background_runtime() {
    let root = tempfile::tempdir().unwrap();
    let store = StateStore::new(root.path());
    store.init_run(init_request()).unwrap();

    let changed = store
        .wait_for_change_with("run-wait", 0, 240, || 0, |_| {})
        .unwrap();
    assert_eq!(changed.status, WaitForChangeStatus::Changed);
    assert_eq!(changed.current_revision, 1);

    let clock = Rc::new(Cell::new(0_u64));
    let now_clock = Rc::clone(&clock);
    let sleep_clock = Rc::clone(&clock);
    let timed_out = store
        .wait_for_change_with(
            "run-wait",
            1,
            4,
            move || now_clock.get(),
            move |millis| sleep_clock.set(sleep_clock.get() + millis),
        )
        .unwrap();
    assert_eq!(timed_out.status, WaitForChangeStatus::Timeout);
    assert_eq!(timed_out.current_revision, 1);
    assert_eq!(clock.get(), 4_000);
}

fn init_request() -> InitRunRequest {
    InitRunRequest {
        project: ProjectIdentity {
            project_id: "project-wait".into(),
            name: "Wait test".into(),
            repository_url: None,
            last_known_path: "C:/work/wait".into(),
        },
        run_id: "run-wait".into(),
        predecessor_run_id: None,
        run_name: None,
        run_description: None,
        source_kind: Some("solo".into()),
        source_project_name: None,
        goal: "Prove bounded read waiting".into(),
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
            objective: "Wait".into(),
        }],
        supervisor: RoleIdentity {
            role_instance_id: "supervisor-wait".into(),
            role: Role::Supervisor,
            agent_runtime: "codex".into(),
            provider: "openai".into(),
            model: "gpt-5.6-sol".into(),
            reasoning: "xhigh".into(),
            session_id: "session-supervisor-wait".into(),
        },
        supervisor_endpoint: EndpointIdentity {
            endpoint_version: 1,
            transport_adapter: "codex-app-server".into(),
            host_identity: "host-a".into(),
            session_id: "session-supervisor-wait".into(),
            native_address: json!({"thread_id":"thread-supervisor-wait"}),
        },
        occurred_at: "2026-09-22T00:00:00Z".into(),
    }
}
