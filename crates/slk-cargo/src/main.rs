use std::env;
use std::process::ExitCode;

use slk_cargo::{help, parse_cli};

fn main() -> ExitCode {
    let arguments = env::args_os().skip(1).collect::<Vec<_>>();
    if matches!(
        arguments.first().and_then(|value| value.to_str()),
        Some("--help" | "-h" | "help")
    ) {
        println!("{}", help());
        return ExitCode::SUCCESS;
    }
    match parse_cli(arguments) {
        Ok(_) => {
            eprintln!("SLK_CARGO_NOT_READY: execution is not available in this intermediate build");
            ExitCode::FAILURE
        }
        Err(error) => {
            eprintln!("{error}");
            ExitCode::FAILURE
        }
    }
}
