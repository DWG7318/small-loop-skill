use std::env;
use std::path::PathBuf;
use std::process::ExitCode;

use serde_json::{json, Value};
use slk_state_core::config::{default_config_path, resolve_data_root_at};
use slk_state_core::write::StateStore;

fn main() -> ExitCode {
    match run() {
        Ok(value) => {
            println!(
                "{}",
                serde_json::to_string(&value).expect("serialize response")
            );
            ExitCode::SUCCESS
        }
        Err(error) => {
            eprintln!(
                "{}",
                serde_json::to_string(&json!({
                    "status":"error",
                    "code":error.code,
                    "message":error.message
                }))
                .expect("serialize error")
            );
            ExitCode::FAILURE
        }
    }
}

#[derive(Debug)]
struct QueryError {
    code: &'static str,
    message: String,
}

impl QueryError {
    fn usage(message: impl Into<String>) -> Self {
        Self {
            code: "SLK_QUERY_USAGE",
            message: message.into(),
        }
    }

    fn command(error: impl std::fmt::Display) -> Self {
        Self {
            code: "SLK_QUERY_FAILED",
            message: error.to_string(),
        }
    }
}

fn run() -> Result<Value, QueryError> {
    let arguments = env::args().skip(1).collect::<Vec<_>>();
    let command = arguments
        .first()
        .map(String::as_str)
        .ok_or_else(|| QueryError::usage(help()))?;
    if matches!(command, "--help" | "-h" | "help") {
        return Ok(json!({"status":"ok","help":help()}));
    }
    let store = configured_store()?;
    match command {
        "projects" => store.projects_view().map_err(QueryError::command),
        "runs" => {
            let project = optional_value(&arguments[1..], "--project-id");
            store
                .runs_view(project.as_deref())
                .map_err(QueryError::command)
        }
        "run" => {
            let run_id = required_value(&arguments[1..], "--run-id")?;
            store.run_view(&run_id).map_err(QueryError::command)
        }
        "graph" | "roles" | "plans" | "events" | "evidence" => {
            let run_id = required_value(&arguments[1..], "--run-id")?;
            let result = match command {
                "graph" => store.graph_view(&run_id),
                "roles" => store.roles_view(&run_id),
                "plans" => store.plans_view(&run_id),
                "events" => store.events_view(&run_id),
                "evidence" => store.evidence_view(&run_id),
                _ => unreachable!(),
            };
            result.map_err(QueryError::command)
        }
        _ => Err(QueryError::usage(format!(
            "unknown command {command}\n{}",
            help()
        ))),
    }
}

fn configured_store() -> Result<StateStore, QueryError> {
    let root = resolve_data_root_at(&config_path()?).map_err(QueryError::command)?;
    Ok(StateStore::new(root))
}

fn config_path() -> Result<PathBuf, QueryError> {
    if let Some(path) = env::var_os("SLK_CONFIG_PATH") {
        return Ok(PathBuf::from(path));
    }
    default_config_path().map_err(QueryError::command)
}

fn required_value(arguments: &[String], option: &str) -> Result<String, QueryError> {
    optional_value(arguments, option).ok_or_else(|| QueryError::usage(format!("missing {option}")))
}

fn optional_value(arguments: &[String], option: &str) -> Option<String> {
    let index = arguments.iter().position(|value| value == option)?;
    arguments.get(index + 1).cloned()
}

fn help() -> &'static str {
    "slk-bi-query <projects|runs|run|graph|roles|plans|events|evidence> [--run-id ID] [--project-id ID]"
}
