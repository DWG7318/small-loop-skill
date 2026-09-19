//! Machine-wide SLK data-root configuration.

use std::fs::{self, OpenOptions};
use std::io::Write;
use std::path::{Path, PathBuf};

use directories::BaseDirs;
use serde::{Deserialize, Serialize};
use thiserror::Error;

const CONFIG_SCHEMA: &str = "slk.config/v1";

#[derive(Debug, Error)]
pub enum ConfigError {
    #[error("the SLK data root must be an absolute path: {0}")]
    RelativeDataRoot(PathBuf),
    #[error("the SLK data root is not a directory: {0}")]
    DataRootIsNotDirectory(PathBuf),
    #[error("unsupported SLK configuration schema: {0}")]
    UnsupportedSchema(String),
    #[error("the operating-system local data directory is unavailable")]
    LocalDataDirectoryUnavailable,
    #[error("configuration I/O failed: {0}")]
    Io(#[from] std::io::Error),
    #[error("configuration JSON is invalid: {0}")]
    Json(#[from] serde_json::Error),
}

#[derive(Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct ConfigFile {
    schema_version: String,
    data_root: PathBuf,
}

pub fn default_config_path() -> Result<PathBuf, ConfigError> {
    let base = BaseDirs::new().ok_or(ConfigError::LocalDataDirectoryUnavailable)?;
    Ok(base.data_local_dir().join("SLK").join("config.json"))
}

pub fn validate_data_root(data_root: &Path) -> Result<(), ConfigError> {
    if !data_root.is_absolute() {
        return Err(ConfigError::RelativeDataRoot(data_root.to_path_buf()));
    }
    if data_root.exists() && !data_root.is_dir() {
        return Err(ConfigError::DataRootIsNotDirectory(data_root.to_path_buf()));
    }
    Ok(())
}

pub fn parse_config(contents: &str) -> Result<PathBuf, ConfigError> {
    let config: ConfigFile = serde_json::from_str(contents)?;
    if config.schema_version != CONFIG_SCHEMA {
        return Err(ConfigError::UnsupportedSchema(config.schema_version));
    }
    validate_data_root(&config.data_root)?;
    Ok(config.data_root)
}

pub fn configure_at(config_path: &Path, data_root: &Path) -> Result<PathBuf, ConfigError> {
    validate_data_root(data_root)?;
    fs::create_dir_all(data_root)?;
    let canonical_root = data_root.canonicalize()?;

    let parent = config_path.parent().ok_or_else(|| {
        ConfigError::Io(std::io::Error::new(
            std::io::ErrorKind::InvalidInput,
            "configuration path has no parent directory",
        ))
    })?;
    fs::create_dir_all(parent)?;

    let config = ConfigFile {
        schema_version: CONFIG_SCHEMA.to_string(),
        data_root: canonical_root.clone(),
    };
    let mut bytes = serde_json::to_vec_pretty(&config)?;
    bytes.push(b'\n');

    let temporary_path = config_path.with_extension("json.tmp");
    if temporary_path.exists() {
        fs::remove_file(&temporary_path)?;
    }

    let write_result = (|| -> Result<(), ConfigError> {
        let mut temporary = OpenOptions::new()
            .create_new(true)
            .write(true)
            .open(&temporary_path)?;
        temporary.write_all(&bytes)?;
        temporary.sync_all()?;
        drop(temporary);
        replace_file(&temporary_path, config_path)?;
        Ok(())
    })();

    if write_result.is_err() && temporary_path.exists() {
        let _ = fs::remove_file(&temporary_path);
    }
    write_result?;
    Ok(canonical_root)
}

pub fn resolve_data_root_at(config_path: &Path) -> Result<PathBuf, ConfigError> {
    let configured = parse_config(&fs::read_to_string(config_path)?)?;
    if !configured.is_dir() {
        return Err(ConfigError::DataRootIsNotDirectory(configured));
    }
    Ok(configured.canonicalize()?)
}

#[cfg(windows)]
pub(crate) fn replace_file(source: &Path, destination: &Path) -> Result<(), ConfigError> {
    use std::os::windows::ffi::OsStrExt;

    const MOVEFILE_REPLACE_EXISTING: u32 = 0x1;
    const MOVEFILE_WRITE_THROUGH: u32 = 0x8;

    #[link(name = "Kernel32")]
    extern "system" {
        fn MoveFileExW(
            existing_file_name: *const u16,
            new_file_name: *const u16,
            flags: u32,
        ) -> i32;
    }

    let source: Vec<u16> = source.as_os_str().encode_wide().chain(Some(0)).collect();
    let destination: Vec<u16> = destination
        .as_os_str()
        .encode_wide()
        .chain(Some(0))
        .collect();
    let replaced = unsafe {
        MoveFileExW(
            source.as_ptr(),
            destination.as_ptr(),
            MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH,
        )
    };
    if replaced == 0 {
        return Err(ConfigError::Io(std::io::Error::last_os_error()));
    }
    Ok(())
}

#[cfg(not(windows))]
pub(crate) fn replace_file(source: &Path, destination: &Path) -> Result<(), ConfigError> {
    fs::rename(source, destination)?;
    Ok(())
}
