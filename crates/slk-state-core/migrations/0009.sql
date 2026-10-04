ALTER TABLE overwatcher_bindings RENAME TO overwatcher_bindings_v8;

CREATE TABLE overwatcher_bindings (
    run_id TEXT PRIMARY KEY REFERENCES runs(run_id),
    role_instance_id TEXT NOT NULL UNIQUE,
    agent_runtime TEXT NOT NULL,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    reasoning TEXT NOT NULL,
    session_id TEXT NOT NULL,
    endpoint_version INTEGER NOT NULL CHECK (endpoint_version > 0),
    transport_adapter TEXT NOT NULL,
    host_identity TEXT NOT NULL,
    native_address_json TEXT NOT NULL,
    bound_by_role_instance_id TEXT NOT NULL REFERENCES role_instances(role_instance_id),
    binding_reason TEXT NOT NULL,
    credential_id TEXT NOT NULL UNIQUE,
    credential_sha256 TEXT NOT NULL UNIQUE,
    credential_state TEXT NOT NULL CHECK (credential_state IN ('active', 'revoked')),
    lifecycle_state TEXT NOT NULL CHECK (lifecycle_state IN ('active', 'closed', 'archived')),
    bound_at TEXT NOT NULL,
    closed_at TEXT,
    archive_evidence_ref TEXT,
    observation_mode TEXT CHECK (observation_mode IS NULL OR observation_mode = 'FOREGROUND_ACTIVE_TURN'),
    cadence_seconds INTEGER CHECK (
        cadence_seconds IS NULL OR cadence_seconds BETWEEN 180 AND 300 OR cadence_seconds = 600
    ),
    foreground_turn_id TEXT,
    native_active_session_evidence_ref TEXT,
    binding_revision INTEGER NOT NULL DEFAULT 1 CHECK (binding_revision > 0),
    canonical_task_id TEXT,
    continuity_state TEXT NOT NULL DEFAULT 'ACTIVE'
        CHECK (continuity_state IN ('ACTIVE', 'VIOLATION', 'ARCHIVED'))
);

INSERT INTO overwatcher_bindings
SELECT * FROM overwatcher_bindings_v8;

DROP TABLE overwatcher_bindings_v8;

DROP TRIGGER overwatch_cycles_no_update;
DROP TRIGGER overwatch_cycles_no_delete;
DROP INDEX overwatch_cycles_run_sequence;
ALTER TABLE overwatch_cycles RENAME TO overwatch_cycles_v8;

CREATE TABLE overwatch_cycles (
    cycle_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES runs(run_id),
    overwatcher_role_instance_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    foreground_turn_id TEXT NOT NULL,
    cycle_sequence INTEGER NOT NULL CHECK (cycle_sequence > 0),
    cadence_seconds INTEGER NOT NULL CHECK (
        cadence_seconds BETWEEN 180 AND 300 OR cadence_seconds = 600
    ),
    plan_revision INTEGER NOT NULL CHECK (plan_revision > 0),
    go_id TEXT,
    cell_id TEXT,
    attempt INTEGER CHECK (attempt IS NULL OR attempt > 0),
    token_sequence INTEGER NOT NULL CHECK (token_sequence > 0),
    token_holder_role_instance_id TEXT NOT NULL,
    latest_event_id TEXT NOT NULL,
    latest_message_id TEXT,
    checklist_json TEXT NOT NULL,
    anomaly_codes_json TEXT NOT NULL,
    evidence_refs_json TEXT NOT NULL,
    native_active_session_evidence_ref TEXT NOT NULL,
    payload_sha256 TEXT NOT NULL,
    started_at TEXT NOT NULL,
    completed_at TEXT NOT NULL,
    next_cycle_at TEXT NOT NULL,
    binding_revision INTEGER NOT NULL DEFAULT 1 CHECK (binding_revision > 0),
    runtime_revision INTEGER NOT NULL DEFAULT 1 CHECK (runtime_revision > 0),
    native_liveness TEXT NOT NULL DEFAULT 'IN_PROGRESS'
        CHECK (native_liveness IN ('IN_PROGRESS', 'COMPLETED', 'MISSING', 'MISMATCHED')),
    cadence_health TEXT NOT NULL DEFAULT 'ON_TIME'
        CHECK (cadence_health IN ('ON_TIME', 'LATE')),
    cost_metrics_json TEXT,
    UNIQUE (run_id, cycle_sequence),
    FOREIGN KEY (run_id, go_id, cell_id) REFERENCES cell_nodes(run_id, go_id, cell_id)
);

INSERT INTO overwatch_cycles
SELECT * FROM overwatch_cycles_v8;

DROP TABLE overwatch_cycles_v8;

CREATE INDEX overwatch_cycles_run_sequence
ON overwatch_cycles(run_id, cycle_sequence);

CREATE TRIGGER overwatch_cycles_no_update
BEFORE UPDATE ON overwatch_cycles
BEGIN
    SELECT RAISE(ABORT, 'overwatch_cycles are append-only');
END;

CREATE TRIGGER overwatch_cycles_no_delete
BEFORE DELETE ON overwatch_cycles
BEGIN
    SELECT RAISE(ABORT, 'overwatch_cycles are append-only');
END;
