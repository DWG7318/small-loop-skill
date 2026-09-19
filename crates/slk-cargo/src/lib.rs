//! Per-Run Cargo resource isolation for Small Loop Skill.

mod args;
mod classify;
mod paths;
mod runner;
mod state;

pub use args::{help, parse_cli, CargoInvocation, CleanupCommand, CliCommand, RunCommand};
pub use classify::{classify_contention, ContentionKind};
pub use paths::{
    acquire_run_lease, cleanup_run, resolve_data_root, CargoGuardError, RunLease, RunPaths,
};
pub use runner::{run_cargo, run_cargo_with_state, CargoRunResult, OutputSink, RunnerConfig};
pub use state::StateContext;
