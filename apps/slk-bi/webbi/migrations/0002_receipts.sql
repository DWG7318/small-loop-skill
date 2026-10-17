ALTER TABLE runs ADD COLUMN source_generated_at TEXT;
UPDATE runs SET source_generated_at=updated_at;

CREATE TABLE messages_per_run (
    device_id TEXT NOT NULL REFERENCES devices(device_id),
    message_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    source_kind TEXT NOT NULL CHECK (source_kind IN ('EVENT', 'OW_OBSERVATION')),
    message_type TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    occurred_at TEXT NOT NULL,
    ingested_at TEXT NOT NULL,
    PRIMARY KEY (device_id, run_id, message_id),
    FOREIGN KEY (device_id, run_id) REFERENCES runs(device_id, run_id)
);
INSERT INTO messages_per_run SELECT * FROM messages;
DROP TABLE messages;
ALTER TABLE messages_per_run RENAME TO messages;
CREATE INDEX messages_run_time ON messages(device_id, run_id, occurred_at, message_id);
