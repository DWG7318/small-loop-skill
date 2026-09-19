use std::ffi::{OsStr, OsString};
use std::path::{Path, PathBuf};

use crate::paths::{validate_segment, CargoGuardError};

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CargoInvocation {
    program: OsString,
    arguments: Vec<OsString>,
}

impl CargoInvocation {
    pub fn new(
        program: impl Into<OsString>,
        arguments: Vec<OsString>,
        inherited_target: Option<&OsStr>,
    ) -> Result<Self, CargoGuardError> {
        let program = program.into();
        if program.is_empty() || arguments.is_empty() {
            return Err(CargoGuardError::usage(
                "Cargo program and at least one Cargo argument are required",
            ));
        }
        if inherited_target.is_some() || contains_target_override(&arguments) {
            return Err(CargoGuardError::new(
                "SLK_CARGO_TARGET_OVERRIDE",
                "caller-supplied Cargo target directories are incompatible with Run isolation",
            ));
        }
        Ok(Self { program, arguments })
    }

    pub fn program(&self) -> &OsStr {
        &self.program
    }

    pub fn arguments(&self) -> &[OsString] {
        &self.arguments
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct RunCommand {
    data_root: Option<PathBuf>,
    project_id: String,
    run_id: String,
    cargo_program: OsString,
    cargo_arguments: Vec<OsString>,
    go_id: Option<String>,
    cell_id: Option<String>,
    attempt: Option<u32>,
}

impl RunCommand {
    pub fn data_root(&self) -> Option<&Path> {
        self.data_root.as_deref()
    }

    pub fn project_id(&self) -> &str {
        &self.project_id
    }

    pub fn run_id(&self) -> &str {
        &self.run_id
    }

    pub fn cargo_program(&self) -> &OsStr {
        &self.cargo_program
    }

    pub fn cargo_arguments(&self) -> &[OsString] {
        &self.cargo_arguments
    }

    pub fn go_id(&self) -> Option<&str> {
        self.go_id.as_deref()
    }

    pub fn cell_id(&self) -> Option<&str> {
        self.cell_id.as_deref()
    }

    pub fn attempt(&self) -> Option<u32> {
        self.attempt
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CleanupCommand {
    data_root: Option<PathBuf>,
    project_id: String,
    run_id: String,
}

impl CleanupCommand {
    pub fn data_root(&self) -> Option<&Path> {
        self.data_root.as_deref()
    }

    pub fn project_id(&self) -> &str {
        &self.project_id
    }

    pub fn run_id(&self) -> &str {
        &self.run_id
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum CliCommand {
    Run(RunCommand),
    Cleanup(CleanupCommand),
}

pub fn parse_cli(arguments: Vec<OsString>) -> Result<CliCommand, CargoGuardError> {
    let command = arguments
        .first()
        .and_then(|value| value.to_str())
        .ok_or_else(|| CargoGuardError::usage(help()))?;
    match command {
        "run" => parse_run(&arguments[1..]).map(CliCommand::Run),
        "cleanup" => parse_cleanup(&arguments[1..]).map(CliCommand::Cleanup),
        _ => Err(CargoGuardError::usage(help())),
    }
}

fn parse_run(arguments: &[OsString]) -> Result<RunCommand, CargoGuardError> {
    let delimiter = arguments
        .iter()
        .position(|value| value == "--")
        .ok_or_else(|| CargoGuardError::usage("run requires -- before Cargo arguments"))?;
    let options = &arguments[..delimiter];
    let cargo_arguments = arguments[delimiter + 1..].to_vec();
    if cargo_arguments.is_empty() {
        return Err(CargoGuardError::usage(
            "run requires a Cargo command after --",
        ));
    }
    let parsed = parse_options(options, true)?;
    Ok(RunCommand {
        data_root: parsed.data_root,
        project_id: parsed.project_id,
        run_id: parsed.run_id,
        cargo_program: parsed
            .cargo_program
            .unwrap_or_else(|| OsString::from("cargo")),
        cargo_arguments,
        go_id: parsed.go_id,
        cell_id: parsed.cell_id,
        attempt: parsed.attempt,
    })
}

fn parse_cleanup(arguments: &[OsString]) -> Result<CleanupCommand, CargoGuardError> {
    let parsed = parse_options(arguments, false)?;
    Ok(CleanupCommand {
        data_root: parsed.data_root,
        project_id: parsed.project_id,
        run_id: parsed.run_id,
    })
}

struct ParsedOptions {
    data_root: Option<PathBuf>,
    project_id: String,
    run_id: String,
    cargo_program: Option<OsString>,
    go_id: Option<String>,
    cell_id: Option<String>,
    attempt: Option<u32>,
}

fn parse_options(
    arguments: &[OsString],
    allow_cargo_program: bool,
) -> Result<ParsedOptions, CargoGuardError> {
    let mut data_root = None;
    let mut project_id = None;
    let mut run_id = None;
    let mut cargo_program = None;
    let mut go_id = None;
    let mut cell_id = None;
    let mut attempt = None;
    let mut index = 0;
    while index < arguments.len() {
        let option = arguments[index]
            .to_str()
            .ok_or_else(|| CargoGuardError::usage("options must be valid Unicode"))?;
        let value = arguments
            .get(index + 1)
            .cloned()
            .ok_or_else(|| CargoGuardError::usage(format!("missing value for {option}")))?;
        match option {
            "--data-root" => data_root = Some(PathBuf::from(value)),
            "--project-id" => project_id = value.into_string().ok(),
            "--run-id" => run_id = value.into_string().ok(),
            "--cargo-program" if allow_cargo_program => cargo_program = Some(value),
            "--go-id" if allow_cargo_program => go_id = value.into_string().ok(),
            "--cell-id" if allow_cargo_program => cell_id = value.into_string().ok(),
            "--attempt" if allow_cargo_program => {
                attempt = Some(
                    value
                        .to_string_lossy()
                        .parse::<u32>()
                        .map_err(|_| CargoGuardError::usage("--attempt must be an integer"))?,
                )
            }
            _ => return Err(CargoGuardError::usage(format!("unknown option {option}"))),
        }
        index += 2;
    }
    let project_id = project_id.ok_or_else(|| CargoGuardError::usage("missing --project-id"))?;
    let run_id = run_id.ok_or_else(|| CargoGuardError::usage("missing --run-id"))?;
    validate_segment("project-id", &project_id)?;
    validate_segment("run-id", &run_id)?;
    if let Some(value) = go_id.as_deref() {
        validate_segment("go-id", value)?;
    }
    if let Some(value) = cell_id.as_deref() {
        validate_segment("cell-id", value)?;
    }
    Ok(ParsedOptions {
        data_root,
        project_id,
        run_id,
        cargo_program,
        go_id,
        cell_id,
        attempt,
    })
}

fn contains_target_override(arguments: &[OsString]) -> bool {
    arguments.iter().any(|argument| {
        let value = argument.to_string_lossy();
        value == "--target-dir" || value.starts_with("--target-dir=")
    })
}

pub fn help() -> &'static str {
    "slk-cargo run [--data-root PATH] --project-id ID --run-id ID [--go-id ID --cell-id ID --attempt N] [--cargo-program PATH] -- <cargo arguments>\nslk-cargo cleanup [--data-root PATH] --project-id ID --run-id ID\nState events are attempted only when SLK_ROLE_CREDENTIAL is present."
}
