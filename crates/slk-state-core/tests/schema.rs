use std::fs;

use rusqlite::{params, Connection, OpenFlags};

use slk_state_core::schema::{create_migration_backup, open_database};

const TABLES: [&str; 19] = [
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
    "overwatcher_bindings",
    "operational_observations",
    "overwatch_cycles",
    "run_lineage",
    "run_identity_reconciliation_receipts",
    "run_method_adoption_receipts",
    "transport_start_receipts",
    "run_runtime_snapshots",
];

fn scalar_text(connection: &Connection, sql: &str) -> String {
    connection
        .query_row(sql, [], |row| row.get::<_, String>(0))
        .expect("text scalar")
}

#[test]
fn database_enables_wal_foreign_keys_and_all_current_tables() {
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
        7
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
    let start_receipt_triggers: i64 = database
        .query_row(
            "SELECT COUNT(*) FROM sqlite_schema WHERE type='trigger' AND name LIKE 'transport_start_receipts_no_%'",
            [],
            |row| row.get(0),
        )
        .unwrap();
    assert_eq!(start_receipt_triggers, 2);
    let runtime_snapshot_triggers: i64 = database
        .query_row(
            "SELECT COUNT(*) FROM sqlite_schema WHERE type='trigger' AND name LIKE 'run_runtime_snapshots_no_%'",
            [],
            |row| row.get(0),
        )
        .unwrap();
    assert_eq!(runtime_snapshot_triggers, 2);
}

#[test]
fn administration_receipts_are_append_only_at_the_database_boundary() {
    let root = tempfile::tempdir().expect("temporary data root");
    let database = open_database(root.path()).expect("open state database");
    seed_history(&database);
    database
        .execute(
            "INSERT INTO run_identity_reconciliation_receipts
             (receipt_id, canonical_run_id, canonical_snapshot_json, source_snapshots_json,
              owner_authorization_json, reason, payload_sha256, occurred_at)
             VALUES ('reconcile-a','run-a','{}','[]','{}','reason','hash','2026-09-20T00:00:01Z')",
            [],
        )
        .unwrap();
    database
        .execute(
            "INSERT INTO run_method_adoption_receipts
             (receipt_id, run_id, expected_snapshot_json, from_version, to_version,
              owner_authorization_json, reconciliation_receipt_id, compatibility_json,
              reason, payload_sha256, occurred_at)
             VALUES ('adopt-a','run-a','{}','4.2.1','4.2.2','{}','reconcile-a','{}',
                     'reason','hash','2026-09-20T00:00:02Z')",
            [],
        )
        .unwrap();

    assert!(database
        .execute(
            "UPDATE run_identity_reconciliation_receipts SET reason='forged'",
            [],
        )
        .is_err());
    assert!(database
        .execute("DELETE FROM run_identity_reconciliation_receipts", [])
        .is_err());
    assert!(database
        .execute(
            "UPDATE run_method_adoption_receipts SET reason='forged'",
            []
        )
        .is_err());
    assert!(database
        .execute("DELETE FROM run_method_adoption_receipts", [])
        .is_err());
}

#[test]
fn operational_observations_are_append_only_at_the_database_boundary() {
    let root = tempfile::tempdir().expect("temporary data root");
    let database = open_database(root.path()).expect("open state database");
    seed_history(&database);
    database
        .execute(
            "INSERT INTO overwatcher_bindings
         (run_id, role_instance_id, agent_runtime, provider, model, reasoning, session_id,
          endpoint_version, transport_adapter, host_identity, native_address_json,
          bound_by_role_instance_id, binding_reason, credential_id, credential_sha256,
          credential_state, lifecycle_state, bound_at)
         VALUES ('run-a','overwatcher-a','codex','openai','gpt-5.6-sol','xhigh',
                 'session-overwatcher-a',1,'native','host-a','{}','role-a','test binding',
                 'credential-a','aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
                 'active','active','2026-09-20T00:00:00Z')",
            [],
        )
        .unwrap();
    database
        .execute(
            "INSERT INTO operational_observations
         (observation_id, run_id, overwatcher_role_instance_id, plan_revision, kind,
          evidence_refs_json, details_json, payload_sha256, occurred_at)
         VALUES ('observation-a','run-a','overwatcher-a',1,'ACTIVITY_UNPROVEN',
                 '[\"evidence-a\"]','{}','hash','2026-09-20T00:00:01Z')",
            [],
        )
        .unwrap();

    assert!(database
        .execute(
            "UPDATE operational_observations SET details_json='{\"forged\":true}'",
            [],
        )
        .is_err());
    assert!(database
        .execute("DELETE FROM operational_observations", [])
        .is_err());
}

#[test]
fn overwatch_cycles_are_append_only_at_the_database_boundary() {
    let root = tempfile::tempdir().expect("temporary data root");
    let database = open_database(root.path()).expect("open state database");
    seed_history(&database);
    database
        .execute(
            "INSERT INTO overwatch_cycles
             (cycle_id, run_id, overwatcher_role_instance_id, session_id,
              foreground_turn_id, cycle_sequence, cadence_seconds, plan_revision,
              token_sequence, token_holder_role_instance_id, latest_event_id,
              checklist_json, anomaly_codes_json, evidence_refs_json,
              native_active_session_evidence_ref, payload_sha256, started_at,
              completed_at, next_cycle_at)
             VALUES ('cycle-a','run-a','overwatcher-a','session-a','turn-a',1,240,1,
                     1,'role-a','work-a','{}','[]','[\"evidence-a\"]',
                     'native:active','hash','2026-09-20T00:00:00Z',
                     '2026-09-20T00:00:01Z','2026-09-20T00:04:01Z')",
            [],
        )
        .unwrap();
    assert!(database
        .execute("UPDATE overwatch_cycles SET checklist_json='[]'", [])
        .is_err());
    assert!(database
        .execute("DELETE FROM overwatch_cycles", [])
        .is_err());
}

#[test]
fn future_nonzero_migration_can_create_and_validate_a_backup() {
    let root = tempfile::tempdir().expect("temporary data root");
    let database = open_database(root.path()).expect("open state database");
    seed_history(&database);

    let backup = create_migration_backup(&database, root.path(), 7, 8, "20260920T000000Z")
        .expect("migration backup");
    let copy = Connection::open_with_flags(backup, rusqlite::OpenFlags::SQLITE_OPEN_READ_ONLY)
        .expect("open backup");
    let count: i64 = copy
        .query_row("SELECT COUNT(*) FROM work_events", [], |row| row.get(0))
        .unwrap();
    assert_eq!(count, 1);
}

#[test]
fn v1_database_migrates_run_identity_and_archive_fields_without_losing_rows() {
    let root = tempfile::tempdir().expect("temporary data root");
    let database_path = root.path().join("slk.db");
    let database = Connection::open(&database_path).unwrap();
    database
        .execute_batch(include_str!("../migrations/0001.sql"))
        .unwrap();
    database.pragma_update(None, "user_version", 1).unwrap();
    seed_history(&database);
    database
        .execute(
            "INSERT INTO go_nodes (run_id, go_id, ordinal, title, objective, state) VALUES ('run-a', 'GO-001', 1, 'Concise Run', 'objective', 'planned')",
            [],
        )
        .unwrap();
    drop(database);

    let migrated = open_database(root.path()).unwrap();
    let values: (
        String,
        String,
        Option<String>,
        String,
        Option<String>,
        String,
        String,
    ) = migrated
        .query_row(
            "SELECT run_name, slk_version, archived_at, source_kind, source_project_name,
                    origin_slk_version,
                    run_description FROM runs WHERE run_id='run-a'",
            [],
            |row| {
                Ok((
                    row.get(0)?,
                    row.get(1)?,
                    row.get(2)?,
                    row.get(3)?,
                    row.get(4)?,
                    row.get(5)?,
                    row.get(6)?,
                ))
            },
        )
        .unwrap();
    assert_eq!(values.0, "Concise Run");
    assert_eq!(values.1, "4.0.0");
    assert_eq!(values.2, None);
    assert_eq!(values.3, "solo");
    assert_eq!(values.4, None);
    assert_eq!(values.5, "4.0.0");
    assert_eq!(values.6, "");

    let backups = fs::read_dir(root.path().join("backups"))
        .unwrap()
        .map(|entry| entry.unwrap().path())
        .filter(|path| path.extension().is_some_and(|extension| extension == "db"))
        .collect::<Vec<_>>();
    assert_eq!(backups.len(), 1);
    let backup =
        Connection::open_with_flags(&backups[0], OpenFlags::SQLITE_OPEN_READ_ONLY).unwrap();
    let backup_version: i64 = backup
        .pragma_query_value(None, "user_version", |row| row.get(0))
        .unwrap();
    let backup_runs: i64 = backup
        .query_row("SELECT COUNT(*) FROM runs", [], |row| row.get(0))
        .unwrap();
    assert_eq!(backup_version, 1);
    assert_eq!(backup_runs, 1);
}

#[test]
fn failed_multi_step_migration_keeps_the_original_database_version() {
    let root = tempfile::tempdir().expect("temporary data root");
    let database_path = root.path().join("slk.db");
    let database = Connection::open(&database_path).unwrap();
    database
        .execute_batch(include_str!("../migrations/0001.sql"))
        .unwrap();
    database.pragma_update(None, "user_version", 1).unwrap();
    database
        .execute("ALTER TABLE runs ADD COLUMN run_name TEXT", [])
        .unwrap();
    drop(database);

    assert!(open_database(root.path()).is_err());

    let unchanged =
        Connection::open_with_flags(&database_path, OpenFlags::SQLITE_OPEN_READ_ONLY).unwrap();
    let version: i64 = unchanged
        .pragma_query_value(None, "user_version", |row| row.get(0))
        .unwrap();
    let added_columns: i64 = unchanged
        .query_row(
            "SELECT COUNT(*) FROM pragma_table_info('runs') WHERE name IN ('slk_version', 'run_description')",
            [],
            |row| row.get(0),
        )
        .unwrap();
    assert_eq!(version, 1);
    assert_eq!(added_columns, 0);
    assert_eq!(
        fs::read_dir(root.path().join("backups"))
            .unwrap()
            .map(|entry| entry.unwrap().path())
            .filter(|path| path.extension().is_some_and(|extension| extension == "db"))
            .count(),
        1
    );
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
