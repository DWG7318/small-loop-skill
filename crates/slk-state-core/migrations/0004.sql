CREATE TABLE overwatcher_bindings (
    run_id TEXT PRIMARY KEY REFERENCES runs(run_id),
    role_instance_id TEXT NOT NULL UNIQUE,
    agent_runtime TEXT NOT NULL,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    reasoning TEXT NOT NULL,
    session_id TEXT NOT NULL UNIQUE,
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
    archive_evidence_ref TEXT
);

CREATE TABLE operational_observations (
    observation_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES runs(run_id),
    overwatcher_role_instance_id TEXT NOT NULL,
    go_id TEXT,
    cell_id TEXT,
    attempt INTEGER CHECK (attempt IS NULL OR attempt > 0),
    plan_revision INTEGER NOT NULL CHECK (plan_revision > 0),
    kind TEXT NOT NULL CHECK (kind IN (
        'DELIVERY_UNCONFIRMED',
        'DELIVERY_RETRYING',
        'ACTIVITY_UNPROVEN',
        'RECORD_CONFLICT',
        'RECOVERY_ESCALATED',
        'PROJECTION_REFRESH_REQUESTED',
        'OVERWATCHER_CLOSED'
    )),
    related_event_id TEXT,
    message_id TEXT,
    evidence_refs_json TEXT NOT NULL,
    details_json TEXT NOT NULL,
    payload_sha256 TEXT NOT NULL,
    occurred_at TEXT NOT NULL,
    FOREIGN KEY (run_id, go_id, cell_id) REFERENCES cell_nodes(run_id, go_id, cell_id)
);

CREATE INDEX operational_observations_run_time
ON operational_observations(run_id, occurred_at, observation_id);

CREATE TRIGGER operational_observations_no_update
BEFORE UPDATE ON operational_observations
BEGIN
    SELECT RAISE(ABORT, 'operational_observations are append-only');
END;

CREATE TRIGGER operational_observations_no_delete
BEFORE DELETE ON operational_observations
BEGIN
    SELECT RAISE(ABORT, 'operational_observations are append-only');
END;

CREATE TABLE run_lineage (
    successor_run_id TEXT PRIMARY KEY REFERENCES runs(run_id),
    predecessor_run_id TEXT NOT NULL UNIQUE REFERENCES runs(run_id),
    created_at TEXT NOT NULL,
    CHECK (successor_run_id <> predecessor_run_id)
);
