ALTER TABLE runs ADD COLUMN current_runtime_revision INTEGER NOT NULL DEFAULT 1
    CHECK (current_runtime_revision > 0);

CREATE TABLE transport_start_receipts (
    transport_receipt_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES runs(run_id),
    event_id TEXT NOT NULL UNIQUE,
    message_id TEXT NOT NULL,
    go_id TEXT NOT NULL,
    cell_id TEXT NOT NULL,
    attempt INTEGER NOT NULL CHECK (attempt > 0),
    plan_revision INTEGER NOT NULL CHECK (plan_revision > 0),
    runtime_revision INTEGER NOT NULL CHECK (runtime_revision > 0),
    token_sequence INTEGER NOT NULL CHECK (token_sequence > 0),
    from_role_instance_id TEXT NOT NULL REFERENCES role_instances(role_instance_id),
    to_role_instance_id TEXT NOT NULL REFERENCES role_instances(role_instance_id),
    endpoint_version INTEGER NOT NULL CHECK (endpoint_version > 0),
    payload_type TEXT NOT NULL,
    payload_sha256 TEXT NOT NULL,
    evidence_id TEXT NOT NULL,
    evidence_path TEXT NOT NULL,
    evidence_sha256 TEXT NOT NULL,
    endpoint_sha256 TEXT NOT NULL,
    envelope_sha256 TEXT NOT NULL,
    native_status TEXT NOT NULL CHECK (native_status = 'STARTED'),
    request_sha256 TEXT NOT NULL,
    occurred_at TEXT NOT NULL,
    UNIQUE (run_id, message_id),
    UNIQUE (run_id, runtime_revision),
    FOREIGN KEY (run_id, go_id, cell_id) REFERENCES cell_nodes(run_id, go_id, cell_id)
);

CREATE TABLE run_runtime_snapshots (
    run_id TEXT NOT NULL REFERENCES runs(run_id),
    runtime_revision INTEGER NOT NULL CHECK (runtime_revision > 0),
    plan_revision INTEGER NOT NULL CHECK (plan_revision > 0),
    token_sequence INTEGER NOT NULL CHECK (token_sequence > 0),
    token_holder_role_instance_id TEXT NOT NULL,
    latest_event_id TEXT NOT NULL,
    latest_message_id TEXT,
    method_version TEXT NOT NULL,
    overwatcher_binding_revision INTEGER,
    overwatcher_status TEXT,
    committed_at TEXT NOT NULL,
    PRIMARY KEY (run_id, runtime_revision)
);

INSERT INTO run_runtime_snapshots
    (run_id, runtime_revision, plan_revision, token_sequence,
     token_holder_role_instance_id, latest_event_id, latest_message_id,
     method_version, overwatcher_binding_revision, overwatcher_status, committed_at)
SELECT r.run_id, 1, r.current_plan_revision,
       (SELECT t.token_sequence FROM token_events t WHERE t.run_id=r.run_id
        ORDER BY t.token_sequence DESC LIMIT 1),
       (SELECT t.to_role_instance_id FROM token_events t WHERE t.run_id=r.run_id
        ORDER BY t.token_sequence DESC LIMIT 1),
       COALESCE((SELECT w.event_id FROM work_events w WHERE w.run_id=r.run_id
                 ORDER BY w.rowid DESC LIMIT 1), ''),
       (SELECT t.message_id FROM token_events t WHERE t.run_id=r.run_id
        ORDER BY t.token_sequence DESC LIMIT 1),
       r.slk_version,
       NULL,
       CASE WHEN EXISTS (
           SELECT 1 FROM overwatcher_bindings o
           WHERE o.run_id=r.run_id AND o.lifecycle_state='active'
       ) THEN 'ACTIVE' ELSE NULL END,
       r.created_at
FROM runs r;

CREATE TRIGGER transport_start_receipts_no_update
BEFORE UPDATE ON transport_start_receipts
BEGIN SELECT RAISE(ABORT, 'transport_start_receipts are append-only'); END;

CREATE TRIGGER transport_start_receipts_no_delete
BEFORE DELETE ON transport_start_receipts
BEGIN SELECT RAISE(ABORT, 'transport_start_receipts are append-only'); END;

CREATE TRIGGER run_runtime_snapshots_no_update
BEFORE UPDATE ON run_runtime_snapshots
BEGIN SELECT RAISE(ABORT, 'run_runtime_snapshots are append-only'); END;

CREATE TRIGGER run_runtime_snapshots_no_delete
BEFORE DELETE ON run_runtime_snapshots
BEGIN SELECT RAISE(ABORT, 'run_runtime_snapshots are append-only'); END;
