use std::env;
use std::fmt;
use std::fs::{self, OpenOptions};
use std::io::Write;
use std::path::{Path, PathBuf};
use std::process::Child;

use slk_state_core::config::{default_config_path, resolve_data_root_at};
use uuid::Uuid;

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

    fn lease_directory(&self) -> PathBuf {
        self.run_root.join("leases")
    }
}

#[derive(Debug)]
pub struct RunLease {
    path: PathBuf,
    retain: bool,
}

impl RunLease {
    pub(crate) fn retain_for_inspection(&mut self) {
        self.retain = true;
    }

    pub(crate) fn record_child(&self, child: &Child, target: &Path) -> std::io::Result<()> {
        let record = serde_json::json!({
            "schema_version": "slk.cargo-native-process/v1",
            "process": {"pid": child.id(), "creation_time": child_creation_time(child)},
            "target": target,
        });
        let mut file = OpenOptions::new().append(true).open(&self.path)?;
        writeln!(file, "{record}")?;
        file.sync_data()
    }
}

#[cfg(windows)]
fn child_creation_time(child: &Child) -> Option<String> {
    use std::ffi::c_void;
    use std::os::windows::io::AsRawHandle;
    #[link(name = "kernel32")]
    extern "system" {
        fn GetProcessTimes(
            handle: *mut c_void,
            creation: *mut u64,
            exit: *mut u64,
            kernel: *mut u64,
            user: *mut u64,
        ) -> i32;
    }
    let (mut creation, mut exit, mut kernel, mut user) = (0, 0, 0, 0);
    // Child owns a valid native handle even if this short-lived process exits.
    let ok = unsafe {
        GetProcessTimes(
            child.as_raw_handle(),
            &mut creation,
            &mut exit,
            &mut kernel,
            &mut user,
        )
    };
    (ok != 0).then(|| format!("win-filetime:{creation}"))
}

#[cfg(not(windows))]
fn child_creation_time(child: &Child) -> Option<String> {
    let stat = fs::read_to_string(format!("/proc/{}/stat", child.id())).ok()?;
    // comm may contain spaces or parentheses; fields after its last ')' start at3.
    let fields = stat
        .rsplit_once(')')?
        .1
        .split_whitespace()
        .collect::<Vec<_>>();
    Some(format!("proc-start:{}", fields.get(19)?))
}

impl Drop for RunLease {
    fn drop(&mut self) {
        if !self.retain {
            let _ = fs::remove_file(&self.path);
        }
    }
}

pub fn acquire_run_lease(paths: &RunPaths) -> Result<RunLease, CargoGuardError> {
    let directory = paths.lease_directory();
    fs::create_dir_all(&directory).map_err(|error| {
        CargoGuardError::new(
            "SLK_CARGO_LEASE",
            format!("{}: {error}", directory.display()),
        )
    })?;
    let invocation_id = Uuid::new_v4().simple().to_string();
    let path = directory.join(format!("{invocation_id}.lease"));
    let mut file = OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(&path)
        .map_err(|error| CargoGuardError::new("SLK_CARGO_LEASE", error.to_string()))?;
    let created_at = time::OffsetDateTime::now_utc()
        .format(&time::format_description::well_known::Rfc3339)
        .map_err(|error| CargoGuardError::new("SLK_CARGO_LEASE", error.to_string()))?;
    // This identifies a reservation, not a process-liveness verdict. A wrapper
    // can exit while a native child still uses the target directory.
    let record = serde_json::json!({
        "schema_version": "slk.cargo-lease/v1",
        "invocation_id": invocation_id,
        "wrapper_pid": std::process::id(),
        "created_at": created_at,
        "run_root": paths.run_root(),
    });
    writeln!(file, "{record}")
        .map_err(|error| CargoGuardError::new("SLK_CARGO_LEASE", error.to_string()))?;
    Ok(RunLease {
        path,
        retain: false,
    })
}

pub fn cleanup_run(paths: &RunPaths) -> Result<bool, CargoGuardError> {
    if !paths.run_root().exists() {
        return Ok(false);
    }
    let lease_directory = paths.lease_directory();
    if lease_directory.is_dir() {
        let has_lease = fs::read_dir(&lease_directory)
            .map_err(|error| CargoGuardError::new("SLK_CARGO_CLEANUP", error.to_string()))?
            .next()
            .transpose()
            .map_err(|error| CargoGuardError::new("SLK_CARGO_CLEANUP", error.to_string()))?
            .is_some();
        if has_lease {
            return Err(CargoGuardError::new(
                "SLK_CARGO_CLEANUP_UNRESOLVED",
                "a retained lease is not proof of a live process; verify the exact invocation and native children before cleanup; leave this Run runtime intact until resolved",
            ));
        }
    }
    fs::remove_dir_all(paths.cleanup_root()).map_err(|error| {
        CargoGuardError::new(
            "SLK_CARGO_CLEANUP",
            format!("{}: {error}", paths.cleanup_root().display()),
        )
    })?;
    Ok(true)
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
