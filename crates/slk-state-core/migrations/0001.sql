CREATE TABLE projects (
    project_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    repository_url TEXT,
    last_known_path TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE runs (
    run_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(project_id),
    goal TEXT NOT NULL,
    boundaries_json TEXT NOT NULL,
    state TEXT NOT NULL,
    current_plan_revision INTEGER NOT NULL CHECK (current_plan_revision > 0),
    closure_state TEXT NOT NULL,
    created_at TEXT NOT NULL,
    closed_at TEXT
);

CREATE TABLE go_nodes (
    run_id TEXT NOT NULL REFERENCES runs(run_id),
    go_id TEXT NOT NULL,
    ordinal INTEGER NOT NULL CHECK (ordinal > 0),
    title TEXT NOT NULL,
    objective TEXT NOT NULL,
    state TEXT NOT NULL,
    outcome TEXT,
    PRIMARY KEY (run_id, go_id),
    UNIQUE (run_id, ordinal)
);

CREATE TABLE cell_nodes (
    run_id TEXT NOT NULL,
    go_id TEXT NOT NULL,
    cell_id TEXT NOT NULL,
    ordinal INTEGER NOT NULL CHECK (ordinal > 0),
    title TEXT NOT NULL,
    objective TEXT NOT NULL,
    state TEXT NOT NULL,
    attempt INTEGER NOT NULL DEFAULT 1 CHECK (attempt > 0),
    outcome TEXT,
    PRIMARY KEY (run_id, go_id, cell_id),
    UNIQUE (run_id, go_id, ordinal),
    FOREIGN KEY (run_id, go_id) REFERENCES go_nodes(run_id, go_id)
);

CREATE TABLE role_instances (
    role_instance_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES runs(run_id),
    role TEXT NOT NULL CHECK (role IN ('supervisor', 'checker', 'worker')),
    agent_runtime TEXT NOT NULL,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    reasoning TEXT NOT NULL,
    session_id TEXT NOT NULL,
    lifecycle TEXT NOT NULL,
    predecessor_role_instance_id TEXT REFERENCES role_instances(role_instance_id),
    successor_role_instance_id TEXT REFERENCES role_instances(role_instance_id),
    current_go_id TEXT,
    current_cell_id TEXT,
    created_at TEXT NOT NULL,
    takeover_at TEXT,
    exited_at TEXT
);

CREATE UNIQUE INDEX one_active_role_per_run
ON role_instances(run_id, role)
WHERE lifecycle = 'active';

CREATE TABLE plan_revisions (
    run_id TEXT NOT NULL REFERENCES runs(run_id),
    revision INTEGER NOT NULL CHECK (revision > 0),
    author_role_instance_id TEXT NOT NULL REFERENCES role_instances(role_instance_id),
    snapshot_json TEXT NOT NULL,
    reason TEXT NOT NULL,
    previous_revision INTEGER,
    created_at TEXT NOT NULL,
    PRIMARY KEY (run_id, revision),
    CHECK (previous_revision IS NULL OR previous_revision < revision)
);

CREATE TABLE role_credentials (
    credential_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES runs(run_id),
    role_instance_id TEXT NOT NULL REFERENCES role_instances(role_instance_id),
    credential_sha256 TEXT NOT NULL UNIQUE,
    state TEXT NOT NULL CHECK (state IN ('active', 'revoked')),
    issued_at TEXT NOT NULL,
    revoked_at TEXT
);

CREATE UNIQUE INDEX one_active_credential_per_role
ON role_credentials(role_instance_id)
WHERE state = 'active';

CREATE TABLE role_endpoints (
    run_id TEXT NOT NULL REFERENCES runs(run_id),
    role_instance_id TEXT NOT NULL REFERENCES role_instances(role_instance_id),
    endpoint_version INTEGER NOT NULL CHECK (endpoint_version > 0),
    transport_adapter TEXT NOT NULL,
    host_identity TEXT NOT NULL,
    session_id TEXT NOT NULL,
    native_address_json TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('active', 'retired')),
    created_at TEXT NOT NULL,
    retired_at TEXT,
    PRIMARY KEY (role_instance_id, endpoint_version)
);

CREATE UNIQUE INDEX one_active_endpoint_per_role
ON role_endpoints(role_instance_id)
WHERE state = 'active';

CREATE TABLE token_events (
    event_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES runs(run_id),
    token_sequence INTEGER NOT NULL CHECK (token_sequence > 0),
    from_role_instance_id TEXT REFERENCES role_instances(role_instance_id),
    to_role_instance_id TEXT NOT NULL REFERENCES role_instances(role_instance_id),
    go_id TEXT,
    cell_id TEXT,
    message_id TEXT,
    endpoint_version INTEGER,
    event_type TEXT NOT NULL,
    payload_type TEXT NOT NULL,
    payload_sha256 TEXT NOT NULL,
    payload_location TEXT,
    occurred_at TEXT NOT NULL,
    UNIQUE (run_id, token_sequence)
);

CREATE TABLE work_events (
    event_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES runs(run_id),
    go_id TEXT,
    cell_id TEXT,
    attempt INTEGER CHECK (attempt IS NULL OR attempt > 0),
    plan_revision INTEGER NOT NULL CHECK (plan_revision > 0),
    author_role_instance_id TEXT NOT NULL REFERENCES role_instances(role_instance_id),
    event_type TEXT NOT NULL,
    details_json TEXT NOT NULL,
    corrects_event_id TEXT REFERENCES work_events(event_id),
    occurred_at TEXT NOT NULL,
    FOREIGN KEY (run_id, plan_revision) REFERENCES plan_revisions(run_id, revision)
);

CREATE TABLE evidence (
    evidence_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(project_id),
    run_id TEXT NOT NULL REFERENCES runs(run_id),
    go_id TEXT,
    cell_id TEXT,
    producing_role_instance_id TEXT NOT NULL REFERENCES role_instances(role_instance_id),
    evidence_type TEXT NOT NULL,
    stored_path TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    byte_length INTEGER NOT NULL CHECK (byte_length >= 0),
    corrects_evidence_id TEXT REFERENCES evidence(evidence_id),
    created_at TEXT NOT NULL
);

CREATE TRIGGER plan_revisions_no_update BEFORE UPDATE ON plan_revisions
BEGIN SELECT RAISE(ABORT, 'plan_revisions is append-only'); END;
CREATE TRIGGER plan_revisions_no_delete BEFORE DELETE ON plan_revisions
BEGIN SELECT RAISE(ABORT, 'plan_revisions is append-only'); END;

CREATE TRIGGER token_events_no_update BEFORE UPDATE ON token_events
BEGIN SELECT RAISE(ABORT, 'token_events is append-only'); END;
CREATE TRIGGER token_events_no_delete BEFORE DELETE ON token_events
BEGIN SELECT RAISE(ABORT, 'token_events is append-only'); END;

CREATE TRIGGER work_events_no_update BEFORE UPDATE ON work_events
BEGIN SELECT RAISE(ABORT, 'work_events is append-only'); END;
CREATE TRIGGER work_events_no_delete BEFORE DELETE ON work_events
BEGIN SELECT RAISE(ABORT, 'work_events is append-only'); END;

CREATE TRIGGER evidence_no_update BEFORE UPDATE ON evidence
BEGIN SELECT RAISE(ABORT, 'evidence is append-only'); END;
CREATE TRIGGER evidence_no_delete BEFORE DELETE ON evidence
BEGIN SELECT RAISE(ABORT, 'evidence is append-only'); END;
