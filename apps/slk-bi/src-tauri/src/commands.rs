use std::env;
use std::path::{Path, PathBuf};
use std::time::Duration;

use serde_json::{json, Value};
use slk_state_core::config::{default_config_path, resolve_data_root_at};
use slk_state_core::write::StateStore;

pub const REGISTERED_READ_COMMANDS: [&str; 9] = [
    "metadata", "projects", "runs", "run", "graph", "roles", "plans", "events", "evidence",
];

const BI_VERSION: &str = "1.1.0";

fn nonempty_env(name: &str) -> Option<String> {
    env::var(name).ok().filter(|value| !value.trim().is_empty())
}

fn fallback_device_name() -> String {
    nonempty_env("COMPUTERNAME")
        .or_else(|| nonempty_env("HOSTNAME"))
        .unwrap_or_else(|| "Local computer".into())
}

fn fallback_device_id(name: &str) -> String {
    let normalized = name
        .chars()
        .map(|character| {
            if character.is_ascii_alphanumeric() || matches!(character, '-' | '_') {
                character.to_ascii_uppercase()
            } else {
                '-'
            }
        })
        .collect::<String>();
    format!("HOST-{}", normalized.trim_matches('-'))
}

#[tauri::command]
pub fn metadata() -> Result<Value, String> {
    let device_name = nonempty_env("SLK_BI_DEVICE_NAME").unwrap_or_else(fallback_device_name);
    let device_id = nonempty_env("SLK_BI_DEVICE_ID").unwrap_or_else(|| fallback_device_id(&device_name));
    Ok(json!({
        "schema_version": "slk.bi.metadata/v1",
        "bi_version": BI_VERSION,
        "device_id": device_id,
        "device_name": device_name,
        "webbi_sync_enabled": nonempty_env("SLK_WEBBI_URL").is_some()
            && nonempty_env("SLK_WEBBI_UPLOAD_TOKEN").is_some()
            && nonempty_env("SLK_BI_DEVICE_ID").is_some()
    }))
}

pub fn validate_sync_payload(payload: &Value, expected_device_id: &str) -> Result<(), String> {
    let object = payload
        .as_object()
        .ok_or_else(|| "SLK_WEBBI_UPLOAD_INVALID".to_string())?;
    let expected = [
        "schema_version",
        "bi_version",
        "upload_id",
        "generated_at",
        "device",
        "runs",
    ];
    if object.len() != expected.len() || expected.iter().any(|key| !object.contains_key(*key)) {
        return Err("SLK_WEBBI_UPLOAD_INVALID".into());
    }
    if object.get("schema_version").and_then(Value::as_str) != Some("slk.bi.upload/v1")
        || object.get("bi_version").and_then(Value::as_str) != Some(BI_VERSION)
    {
        return Err("SLK_WEBBI_UPLOAD_VERSION_UNSUPPORTED".into());
    }
    let device = object
        .get("device")
        .and_then(Value::as_object)
        .ok_or_else(|| "SLK_WEBBI_DEVICE_INVALID".to_string())?;
    if device.len() != 2
        || device.get("device_id").and_then(Value::as_str) != Some(expected_device_id)
        || device
            .get("device_name")
            .and_then(Value::as_str)
            .is_none_or(|name| name.trim().is_empty())
    {
        return Err("SLK_WEBBI_DEVICE_INVALID".into());
    }
    if object
        .get("upload_id")
        .and_then(Value::as_str)
        .is_none_or(|value| value.trim().is_empty())
        || !object.get("runs").is_some_and(Value::is_array)
    {
        return Err("SLK_WEBBI_UPLOAD_INVALID".into());
    }
    if serde_json::to_vec(payload).map_err(|error| error.to_string())?.len() > 10 * 1024 * 1024 {
        return Err("SLK_WEBBI_UPLOAD_TOO_LARGE".into());
    }
    Ok(())
}

fn sync_configuration() -> Result<Option<(String, String, String)>, String> {
    let Some(url) = nonempty_env("SLK_WEBBI_URL") else {
        return Ok(None);
    };
    let Some(token) = nonempty_env("SLK_WEBBI_UPLOAD_TOKEN") else {
        return Ok(None);
    };
    let Some(device_id) = nonempty_env("SLK_BI_DEVICE_ID") else {
        return Ok(None);
    };
    let endpoint = format!("{}/api/v1/uploads", url.trim_end_matches('/'));
    if !(endpoint.starts_with("https://") || endpoint.starts_with("http://localhost")) {
        return Err("SLK_WEBBI_URL_INVALID".into());
    }
    Ok(Some((endpoint, token, device_id)))
}

#[tauri::command]
pub async fn sync_webbi(payload: Value) -> Result<Value, String> {
    let Some((endpoint, token, device_id)) = sync_configuration()? else {
        return Ok(json!({"status":"disabled","upload_id":Value::Null}));
    };
    validate_sync_payload(&payload, &device_id)?;
    let upload_id = payload
        .get("upload_id")
        .and_then(Value::as_str)
        .expect("validated upload id")
        .to_string();
    let response = reqwest::Client::builder()
        .timeout(Duration::from_secs(15))
        .build()
        .map_err(|_| "SLK_WEBBI_CLIENT_UNAVAILABLE".to_string())?
        .post(endpoint)
        .bearer_auth(token)
        .header("x-slk-upload-id", &upload_id)
        .json(&payload)
        .send()
        .await
        .map_err(|_| "SLK_WEBBI_UPLOAD_FAILED".to_string())?;
    if !response.status().is_success() {
        return Err(format!("SLK_WEBBI_UPLOAD_REJECTED:{}", response.status().as_u16()));
    }
    Ok(json!({"status":"uploaded","upload_id":upload_id}))
}

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
