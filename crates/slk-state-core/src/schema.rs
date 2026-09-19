//! SQLite initialization and versioned schema ownership.

use std::fs;
use std::path::{Path, PathBuf};
use std::time::Duration;

use rusqlite::{Connection, OpenFlags, MAIN_DB};
use thiserror::Error;

use crate::config::{validate_data_root, ConfigError};

pub const SCHEMA_VERSION: i64 = 1;
const MIGRATION_V1: &str = include_str!("../migrations/0001.sql");

#[derive(Debug, Error)]
pub enum SchemaError {
    #[error(transparent)]
    Config(#[from] ConfigError),
    #[error("database I/O failed: {0}")]
    Io(#[from] std::io::Error),
    #[error("SQLite operation failed: {0}")]
    Sqlite(#[from] rusqlite::Error),
    #[error("unsupported SLK database schema version {found}; this binary supports {supported}")]
    UnsupportedVersion { found: i64, supported: i64 },
    #[error("invalid migration range v{from} to v{to}")]
    InvalidMigrationRange { from: i64, to: i64 },
}

pub fn database_path(data_root: &Path) -> PathBuf {
    data_root.join("slk.db")
}

pub fn open_database(data_root: &Path) -> Result<Connection, SchemaError> {
    validate_data_root(data_root)?;
    fs::create_dir_all(data_root)?;

    let mut connection = Connection::open(database_path(data_root))?;
    connection.busy_timeout(Duration::from_secs(5))?;
    connection.pragma_update(None, "foreign_keys", true)?;
    connection.pragma_update(None, "journal_mode", "WAL")?;

    let version: i64 = connection.pragma_query_value(None, "user_version", |row| row.get(0))?;
    match version {
        SCHEMA_VERSION => {}
        0 => apply_v1(&mut connection)?,
        found => {
            return Err(SchemaError::UnsupportedVersion {
                found,
                supported: SCHEMA_VERSION,
            });
        }
    }

    Ok(connection)
}

pub fn create_migration_backup(
    connection: &Connection,
    data_root: &Path,
    from: i64,
    to: i64,
    timestamp: &str,
) -> Result<PathBuf, SchemaError> {
    if from <= 0 || to <= from {
        return Err(SchemaError::InvalidMigrationRange { from, to });
    }
    let backup_directory = data_root.join("backups");
    fs::create_dir_all(&backup_directory)?;
    let backup_path = backup_directory.join(format!("slk-before-v{from}-to-v{to}-{timestamp}.db"));
    connection.backup(MAIN_DB, &backup_path, None)?;

    let validation = Connection::open_with_flags(&backup_path, OpenFlags::SQLITE_OPEN_READ_ONLY)?;
    let integrity: String = validation.query_row("PRAGMA integrity_check", [], |row| row.get(0))?;
    let backup_version: i64 =
        validation.pragma_query_value(None, "user_version", |row| row.get(0))?;
    if integrity != "ok" || backup_version != from {
        return Err(SchemaError::UnsupportedVersion {
            found: backup_version,
            supported: from,
        });
    }
    Ok(backup_path)
}

fn apply_v1(connection: &mut Connection) -> Result<(), SchemaError> {
    let transaction = connection.transaction()?;
    transaction.execute_batch(MIGRATION_V1)?;
    transaction.pragma_update(None, "user_version", SCHEMA_VERSION)?;
    transaction.commit()?;
    Ok(())
}
