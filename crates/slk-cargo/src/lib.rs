//! Per-Run Cargo resource isolation for Small Loop Skill.

mod args;
mod classify;
mod paths;
mod runner;

pub use args::{help, parse_cli, CargoInvocation, CleanupCommand, CliCommand, RunCommand};
pub use classify::{classify_contention, ContentionKind};
pub use paths::{resolve_data_root, CargoGuardError, RunPaths};
pub use runner::{run_cargo, CargoRunResult, OutputSink, RunnerConfig};
