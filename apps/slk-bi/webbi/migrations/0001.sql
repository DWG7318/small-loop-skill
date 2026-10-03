CREATE TABLE devices (
    device_id TEXT PRIMARY KEY,
    device_name TEXT NOT NULL,
    registered_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL
);

CREATE TABLE runs (
    device_id TEXT NOT NULL REFERENCES devices(device_id),
    run_id TEXT NOT NULL,
    archived INTEGER NOT NULL CHECK (archived IN (0, 1)),
    payload_json TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (device_id, run_id)
);

CREATE INDEX runs_archive_update ON runs(archived, updated_at DESC);

CREATE TABLE messages (
    device_id TEXT NOT NULL REFERENCES devices(device_id),
    message_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    source_kind TEXT NOT NULL CHECK (source_kind IN ('EVENT', 'OW_OBSERVATION')),
    message_type TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    occurred_at TEXT NOT NULL,
    ingested_at TEXT NOT NULL,
    PRIMARY KEY (device_id, message_id),
    FOREIGN KEY (device_id, run_id) REFERENCES runs(device_id, run_id)
);

CREATE INDEX messages_run_time ON messages(device_id, run_id, occurred_at, message_id);

CREATE TABLE notification_settings (
    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
    enabled INTEGER NOT NULL CHECK (enabled IN (0, 1)),
    server_url TEXT NOT NULL,
    topic TEXT NOT NULL,
    auth_mode TEXT NOT NULL CHECK (auth_mode IN ('none', 'token', 'password')),
    username TEXT,
    encrypted_secret TEXT,
    secret_iv TEXT,
    selection_mode TEXT NOT NULL CHECK (selection_mode IN ('all', 'selected')),
    selected_message_types_json TEXT NOT NULL,
    config_version INTEGER NOT NULL CHECK (config_version >= 0),
    updated_at TEXT NOT NULL
);

CREATE TABLE notification_deliveries (
    delivery_key TEXT PRIMARY KEY,
    status TEXT NOT NULL CHECK (status IN ('sent', 'failed')),
    error TEXT,
    attempted_at TEXT NOT NULL
);
