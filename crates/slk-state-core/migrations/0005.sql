ALTER TABLE overwatcher_bindings ADD COLUMN observation_mode TEXT
    CHECK (observation_mode IS NULL OR observation_mode = 'FOREGROUND_ACTIVE_TURN');
ALTER TABLE overwatcher_bindings ADD COLUMN cadence_seconds INTEGER
    CHECK (cadence_seconds IS NULL OR cadence_seconds BETWEEN 180 AND 300);
ALTER TABLE overwatcher_bindings ADD COLUMN foreground_turn_id TEXT;
ALTER TABLE overwatcher_bindings ADD COLUMN native_active_session_evidence_ref TEXT;

CREATE TABLE overwatch_cycles (
    cycle_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES runs(run_id),
    overwatcher_role_instance_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    foreground_turn_id TEXT NOT NULL,
    cycle_sequence INTEGER NOT NULL CHECK (cycle_sequence > 0),
    cadence_seconds INTEGER NOT NULL CHECK (cadence_seconds BETWEEN 180 AND 300),
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
    UNIQUE (run_id, cycle_sequence),
    FOREIGN KEY (run_id, go_id, cell_id) REFERENCES cell_nodes(run_id, go_id, cell_id)
);

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
