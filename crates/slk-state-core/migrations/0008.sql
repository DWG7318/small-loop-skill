CREATE TABLE overwatcher_credential_rotations (
    rotation_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES runs(run_id),
    binding_revision INTEGER NOT NULL CHECK (binding_revision > 0),
    role_instance_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    foreground_turn_id TEXT NOT NULL,
    old_credential_id TEXT NOT NULL,
    new_credential_id TEXT NOT NULL UNIQUE,
    runtime_revision INTEGER NOT NULL CHECK (runtime_revision > 0),
    evidence_path TEXT NOT NULL,
    evidence_sha256 TEXT NOT NULL,
    reason TEXT NOT NULL,
    occurred_at TEXT NOT NULL
);

CREATE TRIGGER overwatcher_credential_rotations_no_update
BEFORE UPDATE ON overwatcher_credential_rotations
BEGIN SELECT RAISE(ABORT, 'overwatcher_credential_rotations are append-only'); END;

CREATE TRIGGER overwatcher_credential_rotations_no_delete
BEFORE DELETE ON overwatcher_credential_rotations
BEGIN SELECT RAISE(ABORT, 'overwatcher_credential_rotations are append-only'); END;
