use std::env;
use std::fmt;
use std::path::{Path, PathBuf};

use slk_state_core::config::{default_config_path, resolve_data_root_at};

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CargoGuardError {
    code: &'static str,
    message: String,
}

impl CargoGuardError {
    pub(crate) fn new(code: &'static str, message: impl Into<String>) -> Self {
        Self {
            code,
            message: message.into(),
        }
    }

    pub(crate) fn usage(message: impl Into<String>) -> Self {
        Self::new("SLK_CARGO_USAGE", message)
    }

    pub fn code(&self) -> &'static str {
        self.code
    }

    pub fn message(&self) -> &str {
        &self.message
    }
}

impl fmt::Display for CargoGuardError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{}: {}", self.code, self.message)
    }
}

impl std::error::Error for CargoGuardError {}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct RunPaths {
    run_root: PathBuf,
}

impl RunPaths {
    pub fn new(
        data_root: impl AsRef<Path>,
        project_id: &str,
        run_id: &str,
    ) -> Result<Self, CargoGuardError> {
        let data_root = data_root.as_ref();
        if !data_root.is_absolute() {
            return Err(CargoGuardError::new(
                "SLK_CARGO_DATA_ROOT",
                format!("data root must be absolute: {}", data_root.display()),
            ));
        }
        validate_segment("project-id", project_id)?;
        validate_segment("run-id", run_id)?;
        Ok(Self {
            run_root: data_root
                .join("runtime")
                .join("cargo")
                .join(project_id)
                .join(run_id),
        })
    }

    pub fn run_root(&self) -> &Path {
        &self.run_root
    }

    pub fn cleanup_root(&self) -> &Path {
        &self.run_root
    }

    pub fn primary_target(&self) -> PathBuf {
        self.run_root.join("primary")
    }

    pub fn recovery_target(&self, attempt: u32) -> PathBuf {
        self.run_root.join(format!("recovery-{attempt}"))
    }
}

pub fn resolve_data_root(explicit: Option<&Path>) -> Result<PathBuf, CargoGuardError> {
    if let Some(path) = explicit {
        if !path.is_absolute() {
            return Err(CargoGuardError::new(
                "SLK_CARGO_DATA_ROOT",
                format!("data root must be absolute: {}", path.display()),
            ));
        }
        return Ok(path.to_path_buf());
    }
    let config_path = match env::var_os("SLK_CONFIG_PATH") {
        Some(value) => PathBuf::from(value),
        None => default_config_path()
            .map_err(|error| CargoGuardError::new("SLK_CARGO_CONFIG", error.to_string()))?,
    };
    resolve_data_root_at(&config_path)
        .map_err(|error| CargoGuardError::new("SLK_CARGO_CONFIG", error.to_string()))
}

pub(crate) fn validate_segment(label: &str, value: &str) -> Result<(), CargoGuardError> {
    let mut characters = value.chars();
    let valid_first = characters
        .next()
        .is_some_and(|character| character.is_ascii_alphanumeric());
    let valid_rest = characters
        .all(|character| character.is_ascii_alphanumeric() || matches!(character, '-' | '_' | '.'));
    if valid_first && valid_rest {
        Ok(())
    } else {
        Err(CargoGuardError::new(
            "SLK_CARGO_IDENTIFIER",
            format!("{label} must be one safe ASCII path segment"),
        ))
    }
}
