use std::path::{Path, PathBuf};

use serde_json::Value;
use slk_state_core::config::{default_config_path, resolve_data_root_at};
use slk_state_core::write::StateStore;

pub const REGISTERED_READ_COMMANDS: [&str; 8] = [
    "projects", "runs", "run", "graph", "roles", "plans", "events", "evidence",
];

fn store_from(config_path: &Path) -> Result<StateStore, String> {
    let root = resolve_data_root_at(config_path).map_err(|error| error.to_string())?;
    Ok(StateStore::new(root))
}

fn default_path() -> Result<PathBuf, String> {
    default_config_path().map_err(|error| error.to_string())
}

pub fn projects_from(config_path: &Path) -> Result<Value, String> {
    store_from(config_path)?
        .projects_view()
        .map_err(|error| error.to_string())
}

pub fn runs_from(config_path: &Path, project_id: Option<String>) -> Result<Value, String> {
    store_from(config_path)?
        .runs_view(project_id.as_deref())
        .map_err(|error| error.to_string())
}

fn run_from(config_path: &Path, run_id: &str, view: &str) -> Result<Value, String> {
    let store = store_from(config_path)?;
    let result = match view {
        "run" => store.run_view(run_id),
        "graph" => store.graph_view(run_id),
        "roles" => store.roles_view(run_id),
        "plans" => store.plans_view(run_id),
        "events" => store.events_view(run_id),
        "evidence" => store.evidence_view(run_id),
        _ => unreachable!("registered read view"),
    };
    result.map_err(|error| error.to_string())
}

#[tauri::command]
pub fn projects() -> Result<Value, String> {
    projects_from(&default_path()?)
}

#[tauri::command]
pub fn runs(project_id: Option<String>) -> Result<Value, String> {
    runs_from(&default_path()?, project_id)
}

#[tauri::command]
pub fn run(run_id: String) -> Result<Value, String> {
    run_from(&default_path()?, &run_id, "run")
}

#[tauri::command]
pub fn graph(run_id: String) -> Result<Value, String> {
    run_from(&default_path()?, &run_id, "graph")
}

#[tauri::command]
pub fn roles(run_id: String) -> Result<Value, String> {
    run_from(&default_path()?, &run_id, "roles")
}

#[tauri::command]
pub fn plans(run_id: String) -> Result<Value, String> {
    run_from(&default_path()?, &run_id, "plans")
}

#[tauri::command]
pub fn events(run_id: String) -> Result<Value, String> {
    run_from(&default_path()?, &run_id, "events")
}

#[tauri::command]
pub fn evidence(run_id: String) -> Result<Value, String> {
    run_from(&default_path()?, &run_id, "evidence")
}
