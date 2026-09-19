use rusqlite::{params, Connection};

use slk_state_core::schema::{create_migration_backup, open_database};

const TABLES: [&str; 11] = [
    "projects",
    "runs",
    "go_nodes",
    "cell_nodes",
    "plan_revisions",
    "role_instances",
    "role_credentials",
    "role_endpoints",
    "token_events",
    "work_events",
    "evidence",
];

fn scalar_text(connection: &Connection, sql: &str) -> String {
    connection
        .query_row(sql, [], |row| row.get::<_, String>(0))
        .expect("text scalar")
}

#[test]
fn database_enables_wal_foreign_keys_and_all_v1_tables() {
    let root = tempfile::tempdir().expect("temporary data root");
    let database = open_database(root.path()).expect("open state database");

    assert_eq!(scalar_text(&database, "PRAGMA journal_mode"), "wal");
    let foreign_keys: i64 = database
        .pragma_query_value(None, "foreign_keys", |row| row.get(0))
        .unwrap();
    assert_eq!(foreign_keys, 1);
    assert_eq!(
        database
            .pragma_query_value(None, "user_version", |row| row.get::<_, i64>(0))
            .unwrap(),
        1
    );

    for table in TABLES {
        let count: i64 = database
            .query_row(
                "SELECT COUNT(*) FROM sqlite_schema WHERE type='table' AND name=?1",
                [table],
                |row| row.get(0),
            )
            .expect("table query");
        assert_eq!(count, 1, "missing table {table}");
    }
}

#[test]
fn append_only_history_rejects_update_and_delete() {
    let root = tempfile::tempdir().expect("temporary data root");
    let database = open_database(root.path()).expect("open state database");
    seed_history(&database);

    assert!(database
        .execute("UPDATE work_events SET event_type='X'", [])
        .is_err());
    assert!(database.execute("DELETE FROM token_events", []).is_err());
    assert!(database
        .execute("UPDATE plan_revisions SET reason='X'", [])
        .is_err());
    assert!(database.execute("DELETE FROM evidence", []).is_err());
}

#[test]
fn future_nonzero_migration_can_create_and_validate_a_backup() {
    let root = tempfile::tempdir().expect("temporary data root");
    let database = open_database(root.path()).expect("open state database");
    seed_history(&database);

    let backup = create_migration_backup(&database, root.path(), 1, 2, "20260920T000000Z")
        .expect("migration backup");
    let copy = Connection::open_with_flags(backup, rusqlite::OpenFlags::SQLITE_OPEN_READ_ONLY)
        .expect("open backup");
    let count: i64 = copy
        .query_row("SELECT COUNT(*) FROM work_events", [], |row| row.get(0))
        .unwrap();
    assert_eq!(count, 1);
}

fn seed_history(database: &Connection) {
    database
        .execute(
            "INSERT INTO projects (project_id, name, repository_url, last_known_path, created_at) VALUES (?1, ?2, ?3, ?4, ?5)",
            params!["project-a", "Project A", "https://example.invalid/a", "D:/ProjectA", "2026-09-20T00:00:00Z"],
        )
        .unwrap();
    database
        .execute(
            "INSERT INTO runs (run_id, project_id, goal, boundaries_json, state, current_plan_revision, closure_state, created_at) VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8)",
            params!["run-a", "project-a", "Goal", "{}", "active", 1, "open", "2026-09-20T00:00:00Z"],
        )
        .unwrap();
    database
        .execute(
            "INSERT INTO role_instances (role_instance_id, run_id, role, agent_runtime, provider, model, reasoning, session_id, lifecycle, created_at) VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10)",
            params!["role-a", "run-a", "supervisor", "codex", "openai", "gpt", "xhigh", "thread-a", "active", "2026-09-20T00:00:00Z"],
        )
        .unwrap();
    database
        .execute(
            "INSERT INTO plan_revisions (run_id, revision, author_role_instance_id, snapshot_json, reason, created_at) VALUES (?1, ?2, ?3, ?4, ?5, ?6)",
            params!["run-a", 1, "role-a", "{}", "initial", "2026-09-20T00:00:00Z"],
        )
        .unwrap();
    database
        .execute(
            "INSERT INTO token_events (event_id, run_id, token_sequence, to_role_instance_id, event_type, payload_type, payload_sha256, occurred_at) VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8)",
            params!["token-a", "run-a", 1, "role-a", "TOKEN_CREATED", "run", "hash", "2026-09-20T00:00:00Z"],
        )
        .unwrap();
    database
        .execute(
            "INSERT INTO work_events (event_id, run_id, plan_revision, author_role_instance_id, event_type, details_json, occurred_at) VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7)",
            params!["work-a", "run-a", 1, "role-a", "RUN_STARTED", "{}", "2026-09-20T00:00:00Z"],
        )
        .unwrap();
    database
        .execute(
            "INSERT INTO evidence (evidence_id, project_id, run_id, producing_role_instance_id, evidence_type, stored_path, sha256, byte_length, created_at) VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9)",
            params!["evidence-a", "project-a", "run-a", "role-a", "test", "evidence/a.txt", "hash", 1, "2026-09-20T00:00:00Z"],
        )
        .unwrap();
}
