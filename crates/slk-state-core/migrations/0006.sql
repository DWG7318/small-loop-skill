ALTER TABLE runs ADD COLUMN origin_slk_version TEXT NOT NULL DEFAULT 'unrecorded';

UPDATE runs SET origin_slk_version = slk_version;

CREATE TABLE run_identity_reconciliation_receipts (
    receipt_id TEXT PRIMARY KEY,
    canonical_run_id TEXT NOT NULL REFERENCES runs(run_id),
    canonical_snapshot_json TEXT NOT NULL,
    source_snapshots_json TEXT NOT NULL,
    owner_authorization_json TEXT NOT NULL,
    reason TEXT NOT NULL,
    payload_sha256 TEXT NOT NULL,
    occurred_at TEXT NOT NULL
);

CREATE INDEX run_identity_reconciliation_canonical
ON run_identity_reconciliation_receipts(canonical_run_id, occurred_at, receipt_id);

CREATE TRIGGER run_identity_reconciliation_receipts_no_update
BEFORE UPDATE ON run_identity_reconciliation_receipts
BEGIN
    SELECT RAISE(ABORT, 'run_identity_reconciliation_receipts are append-only');
END;

CREATE TRIGGER run_identity_reconciliation_receipts_no_delete
BEFORE DELETE ON run_identity_reconciliation_receipts
BEGIN
    SELECT RAISE(ABORT, 'run_identity_reconciliation_receipts are append-only');
END;

CREATE TABLE run_method_adoption_receipts (
    receipt_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES runs(run_id),
    expected_snapshot_json TEXT NOT NULL,
    from_version TEXT NOT NULL,
    to_version TEXT NOT NULL,
    owner_authorization_json TEXT NOT NULL,
    reconciliation_receipt_id TEXT REFERENCES run_identity_reconciliation_receipts(receipt_id),
    compatibility_json TEXT NOT NULL,
    reason TEXT NOT NULL,
    payload_sha256 TEXT NOT NULL,
    occurred_at TEXT NOT NULL
);

CREATE INDEX run_method_adoption_run
ON run_method_adoption_receipts(run_id, occurred_at, receipt_id);

CREATE TRIGGER run_method_adoption_receipts_no_update
BEFORE UPDATE ON run_method_adoption_receipts
BEGIN
    SELECT RAISE(ABORT, 'run_method_adoption_receipts are append-only');
END;

CREATE TRIGGER run_method_adoption_receipts_no_delete
BEFORE DELETE ON run_method_adoption_receipts
BEGIN
    SELECT RAISE(ABORT, 'run_method_adoption_receipts are append-only');
END;
