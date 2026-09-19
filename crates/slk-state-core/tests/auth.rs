use rusqlite::{params, Connection};

use slk_state_core::auth::{
    authorize_event, issue_credential, revoke_credential, Credential, StateError,
};
use slk_state_core::model::{EventType, Role};
use slk_state_core::schema::open_database;

#[test]
fn only_current_role_instance_can_author_its_event_types() {
    let (_root, database) = worker_database();
    let issued = issue_credential(&database, "run-a", "worker-a", "2026-09-20T00:00:00Z")
        .expect("worker credential");

    assert_eq!(
        authorize_event(
            &database,
            "run-a",
            &issued.credential,
            EventType::WorkStarted
        )
        .unwrap()
        .role,
        Role::Worker
    );
    assert!(matches!(
        authorize_event(&database, "run-a", &issued.credential, EventType::D1Passed),
        Err(StateError::RoleNotAuthorized { .. })
    ));
    assert!(matches!(
        authorize_event(
            &database,
            "run-a",
            &Credential::from_secret("owner-string"),
            EventType::WorkStarted
        ),
        Err(StateError::CredentialInvalid)
    ));
}

#[test]
fn replacement_revokes_old_credential_without_rewriting_history() {
    let (_root, database) = worker_database();
    let old = issue_credential(&database, "run-a", "worker-a", "2026-09-20T00:00:00Z").unwrap();
    database.execute(
        "INSERT INTO work_events (event_id, run_id, plan_revision, author_role_instance_id, event_type, details_json, occurred_at) VALUES ('event-a', 'run-a', 1, 'worker-a', 'WORK_STARTED', '{}', '2026-09-20T00:00:01Z')",
        [],
    ).unwrap();

    database
        .execute(
            "UPDATE role_instances SET lifecycle='replaced', exited_at=?1 WHERE role_instance_id='worker-a'",
            ["2026-09-20T00:01:00Z"],
        )
        .unwrap();
    database
        .execute(
            "INSERT INTO role_instances (role_instance_id, run_id, role, agent_runtime, provider, model, reasoning, session_id, lifecycle, predecessor_role_instance_id, created_at, takeover_at) VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10, ?11, ?12)",
            params!["worker-b", "run-a", "worker", "dsh", "deepseek", "flash", "high", "session-b", "active", "worker-a", "2026-09-20T00:01:00Z", "2026-09-20T00:01:00Z"],
        )
        .unwrap();
    database
        .execute(
            "UPDATE role_instances SET successor_role_instance_id='worker-b' WHERE role_instance_id='worker-a'",
            [],
        )
        .unwrap();
    revoke_credential(&database, &old.credential_id, "2026-09-20T00:01:00Z").unwrap();
    let new = issue_credential(&database, "run-a", "worker-b", "2026-09-20T00:01:00Z").unwrap();

    assert!(matches!(
        authorize_event(&database, "run-a", &old.credential, EventType::WorkProgress),
        Err(StateError::CredentialRevoked)
    ));
    assert!(authorize_event(&database, "run-a", &new.credential, EventType::WorkProgress).is_ok());
    let historical_author: String = database
        .query_row(
            "SELECT author_role_instance_id FROM work_events WHERE event_id='event-a'",
            [],
            |row| row.get(0),
        )
        .unwrap();
    assert_eq!(historical_author, "worker-a");
}

#[test]
fn identity_shape_is_closed_and_credentials_are_redacted() {
    let unknown = r#"{
        "role_instance_id":"worker-a",
        "role":"worker",
        "agent_runtime":"dsh",
        "provider":"deepseek",
        "model":"flash",
        "reasoning":"high",
        "session_id":"session-a",
        "unexpected":"value"
    }"#;
    assert!(serde_json::from_str::<slk_state_core::model::RoleIdentity>(unknown).is_err());

    let credential = Credential::from_secret("do-not-print");
    let debug = format!("{credential:?}");
    assert!(!debug.contains("do-not-print"));
    assert!(debug.contains("REDACTED"));
}

fn worker_database() -> (tempfile::TempDir, Connection) {
    let root = tempfile::tempdir().expect("temporary data root");
    let database = open_database(root.path()).expect("open database");
    database.execute(
        "INSERT INTO projects (project_id, name, last_known_path, created_at) VALUES ('project-a', 'Project A', 'D:/ProjectA', '2026-09-20T00:00:00Z')",
        [],
    ).unwrap();
    database.execute(
        "INSERT INTO runs (run_id, project_id, goal, boundaries_json, state, current_plan_revision, closure_state, created_at) VALUES ('run-a', 'project-a', 'Goal', '{}', 'active', 1, 'open', '2026-09-20T00:00:00Z')",
        [],
    ).unwrap();
    database.execute(
        "INSERT INTO role_instances (role_instance_id, run_id, role, agent_runtime, provider, model, reasoning, session_id, lifecycle, created_at) VALUES ('supervisor-a', 'run-a', 'supervisor', 'codex', 'openai', 'sol', 'xhigh', 'thread-a', 'active', '2026-09-20T00:00:00Z')",
        [],
    ).unwrap();
    database.execute(
        "INSERT INTO role_instances (role_instance_id, run_id, role, agent_runtime, provider, model, reasoning, session_id, lifecycle, created_at) VALUES ('worker-a', 'run-a', 'worker', 'dsh', 'deepseek', 'flash', 'high', 'session-a', 'active', '2026-09-20T00:00:00Z')",
        [],
    ).unwrap();
    database.execute(
        "INSERT INTO plan_revisions (run_id, revision, author_role_instance_id, snapshot_json, reason, created_at) VALUES ('run-a', 1, 'supervisor-a', '{}', 'initial', '2026-09-20T00:00:00Z')",
        [],
    ).unwrap();
    (root, database)
}
