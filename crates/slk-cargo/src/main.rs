use std::env;
use std::ffi::OsString;
use std::io::{self, Write};
use std::process;

use slk_cargo::{
    cleanup_run, help, parse_cli, resolve_data_root, run_cargo_with_state, CargoGuardError,
    CargoInvocation, CliCommand, OutputSink, RunPaths, RunnerConfig, StateContext,
};
use slk_state_core::auth::Credential;

struct ConsoleSink;

impl OutputSink for ConsoleSink {
    fn stdout(&mut self, bytes: &[u8]) {
        let _ = io::stdout().write_all(bytes);
        let _ = io::stdout().flush();
    }

    fn stderr(&mut self, bytes: &[u8]) {
        let _ = io::stderr().write_all(bytes);
        let _ = io::stderr().flush();
    }
}

fn main() {
    let arguments = env::args_os().skip(1).collect::<Vec<_>>();
    if matches!(
        arguments.first().and_then(|value| value.to_str()),
        Some("--help" | "-h" | "help")
    ) {
        println!("{}", help());
        return;
    }
    match execute(arguments) {
        Ok(code) => process::exit(code),
        Err(error) => {
            eprintln!("{error}");
            process::exit(1);
        }
    }
}

fn execute(arguments: Vec<OsString>) -> Result<i32, CargoGuardError> {
    match parse_cli(arguments)? {
        CliCommand::Run(command) => {
            let data_root = resolve_data_root(command.data_root())?;
            let paths = RunPaths::new(&data_root, command.project_id(), command.run_id())?;
            let invocation = CargoInvocation::new(
                command.cargo_program(),
                command.cargo_arguments().to_vec(),
                env::var_os("CARGO_TARGET_DIR").as_deref(),
            )?;
            let state = env::var("SLK_ROLE_CREDENTIAL").ok().map(|secret| {
                StateContext::new(
                    &data_root,
                    Credential::from_secret(secret),
                    command.run_id(),
                    command.go_id().map(str::to_owned),
                    command.cell_id().map(str::to_owned),
                    command.attempt(),
                )
            });
            let mut sink = ConsoleSink;
            let result = run_cargo_with_state(
                &invocation,
                &paths,
                &RunnerConfig::default_for_cli(),
                &mut sink,
                state.as_ref(),
            )?;
            Ok(result.exit_code().unwrap_or(75))
        }
        CliCommand::Cleanup(command) => {
            let data_root = resolve_data_root(command.data_root())?;
            let paths = RunPaths::new(&data_root, command.project_id(), command.run_id())?;
            let removed = cleanup_run(&paths)?;
            println!(
                "SLK_CARGO_CLEANUP {} {}",
                if removed { "removed" } else { "absent" },
                paths.cleanup_root().display()
            );
            Ok(0)
        }
    }
}
