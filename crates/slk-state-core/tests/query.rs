use serde_json::json;

use slk_state_core::auth::StateError;
use slk_state_core::model::{
    CellDefinition, EndpointIdentity, EventType, GoDefinition, InitRunRequest, ProjectIdentity,
    RegisterRoleRequest, Role, RoleIdentity, TokenHandoffRequest, WriteRequest,
};
use slk_state_core::write::StateStore;

#[test]
fn query_requires_explicit_run_and_returns_stable_order_without_credentials() {
    let fixture = Fixture::new();
    assert!(matches!(
        fixture.store.query_run(""),
        Err(StateError::RunIdRequired)
    ));
    let result = fixture.store.query_run("run-a").unwrap();
    assert_eq!(
        result
            .go_nodes
            .iter()
            .map(|node| node.ordinal)
            .collect::<Vec<_>>(),
        vec![1, 2]
    );
    let serialized = serde_json::to_string(&result).unwrap();
    assert!(!serialized.contains("credential"));
    assert!(!serialized.contains("sha256\":\"slk_"));
}

#[test]
fn working_is_only_the_latest_authored_unfinished_state() {
    let fixture = Fixture::worker_active();
    fixture
        .store
        .write_event(
            &fixture.worker,
            worker_event("work-started", EventType::WorkStarted),
        )
        .unwrap();
    assert_eq!(
        fixture
            .store
            .query_run("run-a")
            .unwrap()
            .role("worker")
            .unwrap()
            .display_state,
        "working"
    );

    fixture
        .store
        .write_event(
            &fixture.worker,
            worker_event("candidate", EventType::CandidateSubmitted),
        )
        .unwrap();
    assert_eq!(
        fixture
            .store
            .query_run("run-a")
            .unwrap()
            .role("worker")
            .unwrap()
            .display_state,
        "completed"
    );
}

struct Fixture {
    _root: tempfile::TempDir,
    store: StateStore,
    supervisor: slk_state_core::auth::Credential,
    checker: slk_state_core::auth::Credential,
    worker: slk_state_core::auth::Credential,
}

impl Fixture {
    fn new() -> Self {
        let root = tempfile::tempdir().unwrap();
        let store = StateStore::new(root.path());
        let initialized = store.init_run(init_request()).unwrap();
        let checker = store
            .register_role(
                &initialized.supervisor_credential,
                register("checker-a", Role::Checker),
            )
            .unwrap();
        let worker = store
            .register_role(&checker.credential, register("worker-a", Role::Worker))
            .unwrap();
        Self {
            _root: root,
            store,
            supervisor: initialized.supervisor_credential,
            checker: checker.credential,
            worker: worker.credential,
        }
    }

    fn worker_active() -> Self {
        let fixture = Self::new();
        fixture
            .store
            .handoff_token(&fixture.supervisor, handoff(2, "supervisor-a", "checker-a"))
            .unwrap();
        fixture
            .store
            .handoff_token(&fixture.checker, handoff(3, "checker-a", "worker-a"))
            .unwrap();
        fixture
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
        goal: "Goal".into(),
        boundaries: json!({}),
        go_nodes: vec![
            GoDefinition {
                go_id: "GO-001".into(),
                ordinal: 1,
                title: "First".into(),
                objective: "First objective".into(),
            },
            GoDefinition {
                go_id: "GO-002".into(),
                ordinal: 2,
                title: "Second".into(),
                objective: "Second objective".into(),
            },
        ],
        cell_nodes: vec![
            CellDefinition {
                go_id: "GO-001".into(),
                cell_id: "CELL-001".into(),
                ordinal: 1,
                title: "First cell".into(),
                objective: "First".into(),
            },
            CellDefinition {
                go_id: "GO-002".into(),
                cell_id: "CELL-002".into(),
                ordinal: 1,
                title: "Second cell".into(),
                objective: "Second".into(),
            },
        ],
        supervisor: identity("supervisor-a", Role::Supervisor),
        supervisor_endpoint: endpoint("supervisor-a"),
        occurred_at: "2026-09-20T00:00:00Z".into(),
    }
}

fn register(id: &str, role: Role) -> RegisterRoleRequest {
    RegisterRoleRequest {
        event_id: format!("register-{id}"),
        run_id: "run-a".into(),
        identity: identity(id, role),
        endpoint: endpoint(id),
        occurred_at: "2026-09-20T00:00:01Z".into(),
    }
}

fn identity(id: &str, role: Role) -> RoleIdentity {
    RoleIdentity {
        role_instance_id: id.into(),
        role,
        agent_runtime: "agent".into(),
        provider: "provider".into(),
        model: "model".into(),
        reasoning: "high".into(),
        session_id: format!("session-{id}"),
    }
}

fn endpoint(id: &str) -> EndpointIdentity {
    EndpointIdentity {
        endpoint_version: 1,
        transport_adapter: "native".into(),
        host_identity: "host-a".into(),
        session_id: format!("session-{id}"),
        native_address: json!({"id":id}),
    }
}

fn handoff(sequence: u64, from: &str, to: &str) -> TokenHandoffRequest {
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
        payload_type: "CELL".into(),
        payload_sha256: format!("hash-{sequence}"),
        payload_location: None,
        occurred_at: "2026-09-20T00:00:02Z".into(),
    }
}

fn worker_event(event_id: &str, event_type: EventType) -> WriteRequest {
    WriteRequest {
        event_id: event_id.into(),
        run_id: "run-a".into(),
        go_id: Some("GO-001".into()),
        cell_id: Some("CELL-001".into()),
        attempt: Some(1),
        plan_revision: 1,
        role_instance_id: "worker-a".into(),
        event_type,
        details: json!({}),
        occurred_at: "2026-09-20T00:00:03Z".into(),
    }
}
