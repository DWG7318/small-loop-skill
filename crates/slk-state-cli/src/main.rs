use std::env;
use std::fs;
use std::path::PathBuf;
use std::process::ExitCode;

use serde::de::DeserializeOwned;
use serde_json::{json, Value};
use slk_state_core::auth::Credential;
use slk_state_core::config::{configure_at, default_config_path, resolve_data_root_at};
use slk_state_core::evidence::{EvidenceRequest, EvidenceState};
use slk_state_core::model::{
    InitRunRequest, RebindSessionRequest, RegisterRoleRequest, ReplaceRoleRequest,
    RevisePlanRequest, TokenHandoffRequest, WriteRequest,
};
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
                    "status": "error",
                    "code": error.code,
                    "message": error.message
                }))
                .expect("serialize error")
            );
            ExitCode::FAILURE
        }
    }
}

#[derive(Debug)]
struct CliError {
    code: &'static str,
    message: String,
}

impl CliError {
    fn usage(message: impl Into<String>) -> Self {
        Self {
            code: "SLK_STATE_USAGE",
            message: message.into(),
        }
    }

    fn command(error: impl std::fmt::Display) -> Self {
        Self {
            code: "SLK_STATE_COMMAND_FAILED",
            message: error.to_string(),
        }
    }
}

fn run() -> Result<Value, CliError> {
    let arguments = env::args().skip(1).collect::<Vec<_>>();
    let command = arguments
        .first()
        .map(String::as_str)
        .ok_or_else(|| CliError::usage(help()))?;
    if matches!(command, "--help" | "-h" | "help") {
        return Ok(json!({"status":"ok","help":help()}));
    }
    match command {
        "configure" => configure(&arguments[1..]),
        "init-run" => init_run(&arguments[1..]),
        "register-role" => register_role(&arguments[1..]),
        "handoff" => handoff(&arguments[1..]),
        "write" => write_event(&arguments[1..]),
        "revise-plan" => revise_plan(&arguments[1..]),
        "replace-role" => replace_role(&arguments[1..]),
        "rebind-session" => rebind_session(&arguments[1..]),
        "register-evidence" => register_evidence(&arguments[1..]),
        "export" => export(&arguments[1..]),
        "verify-evidence" => verify_evidence(&arguments[1..]),
        _ => Err(CliError::usage(format!(
            "unknown command {command}\n{}",
            help()
        ))),
    }
}

fn configure(arguments: &[String]) -> Result<Value, CliError> {
    let data_root = required_path(arguments, "--data-root")?;
    let configured = configure_at(&config_path()?, &data_root).map_err(CliError::command)?;
    Ok(json!({"status":"configured","data_root":configured}))
}

fn init_run(arguments: &[String]) -> Result<Value, CliError> {
    let request: InitRunRequest = request(arguments)?;
    let run_id = request.run_id.clone();
    let store = configured_store()?;
    let initialized = store.init_run(request).map_err(CliError::command)?;
    let export = refresh_export(&store, &run_id);
    Ok(json!({
        "status":"initialized",
        "run_id":run_id,
        "supervisor_credential":initialized.supervisor_credential.expose_secret(),
        "export":export
    }))
}

fn register_role(arguments: &[String]) -> Result<Value, CliError> {
    let request: RegisterRoleRequest = request(arguments)?;
    let run_id = request.run_id.clone();
    let store = configured_store()?;
    let issued = store
        .register_role(&role_credential()?, request)
        .map_err(CliError::command)?;
    Ok(json!({
        "status":"registered",
        "run_id":run_id,
        "role_credential":issued.credential.expose_secret(),
        "credential_id":issued.credential_id,
        "export":refresh_export(&store, &run_id)
    }))
}

fn handoff(arguments: &[String]) -> Result<Value, CliError> {
    let request: TokenHandoffRequest = request(arguments)?;
    let run_id = request.run_id.clone();
    let store = configured_store()?;
    let token = store
        .handoff_token(&role_credential()?, request)
        .map_err(CliError::command)?;
    Ok(json!({"status":"handed_off","token":{
        "sequence":token.sequence,
        "owner_role_instance_id":token.owner_role_instance_id,
        "go_id":token.go_id,
        "cell_id":token.cell_id
    },"export":refresh_export(&store, &run_id)}))
}

fn write_event(arguments: &[String]) -> Result<Value, CliError> {
    let request: WriteRequest = request(arguments)?;
    let run_id = request.run_id.clone();
    let store = configured_store()?;
    store
        .write_event(&role_credential()?, request)
        .map_err(CliError::command)?;
    Ok(json!({"status":"recorded","run_id":run_id,"export":refresh_export(&store, &run_id)}))
}

fn revise_plan(arguments: &[String]) -> Result<Value, CliError> {
    let request: RevisePlanRequest = request(arguments)?;
    let run_id = request.run_id.clone();
    let store = configured_store()?;
    let revision = store
        .revise_plan(&role_credential()?, request)
        .map_err(CliError::command)?;
    Ok(
        json!({"status":"revised","run_id":run_id,"revision":revision,"export":refresh_export(&store, &run_id)}),
    )
}

fn replace_role(arguments: &[String]) -> Result<Value, CliError> {
    let request: ReplaceRoleRequest = request(arguments)?;
    let run_id = request.run_id.clone();
    let store = configured_store()?;
    let issued = store
        .replace_role(&role_credential()?, request)
        .map_err(CliError::command)?;
    Ok(json!({
        "status":"replaced",
        "run_id":run_id,
        "replacement_credential":issued.credential.expose_secret(),
        "credential_id":issued.credential_id,
        "export":refresh_export(&store, &run_id)
    }))
}

fn rebind_session(arguments: &[String]) -> Result<Value, CliError> {
    let request: RebindSessionRequest = request(arguments)?;
    let run_id = request.run_id.clone();
    let role_instance_id = request.role_instance_id.clone();
    let endpoint_version = request.endpoint.endpoint_version;
    let store = configured_store()?;
    store
        .rebind_session(&role_credential()?, request)
        .map_err(CliError::command)?;
    Ok(json!({
        "status":"rebound",
        "run_id":run_id,
        "role_instance_id":role_instance_id,
        "endpoint_version":endpoint_version,
        "export":refresh_export(&store, &run_id)
    }))
}

fn register_evidence(arguments: &[String]) -> Result<Value, CliError> {
    let request: EvidenceRequest = request(arguments)?;
    let run_id = request.run_id.clone();
    let store = configured_store()?;
    let saved = store
        .register_evidence(&role_credential()?, request)
        .map_err(CliError::command)?;
    Ok(json!({
        "status":"registered",
        "run_id":run_id,
        "evidence_id":saved.evidence_id,
        "stored_path":saved.stored_path,
        "sha256":saved.sha256,
        "byte_length":saved.byte_length,
        "export":refresh_export(&store, &run_id)
    }))
}

fn export(arguments: &[String]) -> Result<Value, CliError> {
    let run_id = required_value(arguments, "--run-id")?;
    let store = configured_store()?;
    store
        .authenticate_active_role(&run_id, &role_credential()?)
        .map_err(CliError::command)?;
    let path = store.export_run(&run_id).map_err(CliError::command)?;
    Ok(json!({"status":"exported","run_id":run_id,"path":path}))
}

fn verify_evidence(arguments: &[String]) -> Result<Value, CliError> {
    let run_id = required_value(arguments, "--run-id")?;
    let store = configured_store()?;
    store
        .authenticate_active_role(&run_id, &role_credential()?)
        .map_err(CliError::command)?;
    let run = store.query_run(&run_id).map_err(CliError::command)?;
    let mut results = Vec::new();
    for evidence in run.evidence {
        let state = match store
            .verify_evidence(&evidence.evidence_id)
            .map_err(CliError::command)?
        {
            EvidenceState::PresentAndMatching => "present_and_matching",
            EvidenceState::Missing => "missing",
            EvidenceState::HashMismatch => "hash_mismatch",
        };
        results.push(json!({"evidence_id":evidence.evidence_id,"state":state}));
    }
    Ok(json!({"status":"verified","run_id":run_id,"evidence":results}))
}

fn request<T: DeserializeOwned>(arguments: &[String]) -> Result<T, CliError> {
    let path = required_path(arguments, "--request")?;
    let bytes = fs::read(&path).map_err(CliError::command)?;
    serde_json::from_slice(&bytes).map_err(CliError::command)
}

fn required_path(arguments: &[String], option: &str) -> Result<PathBuf, CliError> {
    required_value(arguments, option).map(PathBuf::from)
}

fn required_value(arguments: &[String], option: &str) -> Result<String, CliError> {
    let index = arguments
        .iter()
        .position(|value| value == option)
        .ok_or_else(|| CliError::usage(format!("missing {option}")))?;
    arguments
        .get(index + 1)
        .cloned()
        .ok_or_else(|| CliError::usage(format!("missing value for {option}")))
}

fn configured_store() -> Result<StateStore, CliError> {
    let root = resolve_data_root_at(&config_path()?).map_err(CliError::command)?;
    Ok(StateStore::new(root))
}

fn config_path() -> Result<PathBuf, CliError> {
    if let Some(path) = env::var_os("SLK_CONFIG_PATH") {
        return Ok(PathBuf::from(path));
    }
    default_config_path().map_err(CliError::command)
}

fn role_credential() -> Result<Credential, CliError> {
    let secret = env::var("SLK_ROLE_CREDENTIAL").map_err(|_| CliError {
        code: "SLK_ROLE_CREDENTIAL_REQUIRED",
        message: "SLK_ROLE_CREDENTIAL must be supplied through the environment".into(),
    })?;
    Ok(Credential::from_secret(secret))
}

fn refresh_export(store: &StateStore, run_id: &str) -> Value {
    match store.export_run(run_id) {
        Ok(path) => json!({"path":path}),
        Err(error) => json!({"warning":error.to_string()}),
    }
}

fn help() -> &'static str {
    "slk-state <configure|init-run|register-role|handoff|write|revise-plan|replace-role|rebind-session|register-evidence|export|verify-evidence> [options]\nCredentials are read only from SLK_ROLE_CREDENTIAL."
}
